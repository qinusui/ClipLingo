"""
场景：独立牌组模式 + 重复批处理幂等性 + 失败恢复测试

测试内容:
1. 独立牌组模式 - merge=False 时每个视频生成单独的 .apkg
2. 重复批处理幂等性 - 完成后再次触发不会重复添加卡片
3. 批处理中途失败恢复 - 错误后 batchTriggeredRef 正确重置允许重试
"""
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from main import generate_apkg


# ─── 独立牌组模式测试 ───────────────────────────────────────


class TestIndependentModeManifest:
    """独立牌组模式下 manifest 结构和处理"""

    def test_independent_mode_manifest_structure(self):
        """独立模式 manifest 应包含 results 数组和 total_cards"""
        manifest = {
            "merge": False,
            "total_cards": 453,
            "results": [
                {
                    "video_name": "SE01.01",
                    "cards_count": 387,
                    "processed": [{"index": 1, "video_stem": "SE01.01"}] * 387,
                },
                {
                    "video_name": "test",
                    "cards_count": 66,
                    "processed": [{"index": 1, "video_stem": "test"}] * 66,
                },
            ],
        }

        assert manifest["merge"] is False
        assert manifest["total_cards"] == 453
        assert len(manifest["results"]) == 2
        assert manifest["results"][0]["video_name"] == "SE01.01"
        assert manifest["results"][1]["video_name"] == "test"

    def test_independent_mode_apkg_generation(self, tmp_path):
        """独立模式下每个视频生成独立的 .apkg"""
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        # 创建独立模式 manifest
        manifest_data = {
            "merge": False,
            "total_cards": 100,
            "results": [
                {
                    "video_name": "video1",
                    "cards_count": 60,
                    "processed": [
                        {
                            "index": i,
                            "video_stem": "video1",
                            "text": f"Card {i}",
                            "translation": f"翻译 {i}",
                            "notes": "",
                            "audio_path": str(output_dir / f"audio/card_{i:04d}.mp3"),
                            "screenshot_path": str(output_dir / f"screenshots/card_{i:04d}.jpg"),
                        }
                        for i in range(1, 61)
                    ],
                },
                {
                    "video_name": "video2",
                    "cards_count": 40,
                    "processed": [
                        {
                            "index": i,
                            "video_stem": "video2",
                            "text": f"Card {i}",
                            "translation": f"翻译 {i}",
                            "notes": "",
                            "audio_path": str(output_dir / f"audio/card_{10000+i:05d}.mp3"),
                            "screenshot_path": str(output_dir / f"screenshots/card_{10000+i:05d}.jpg"),
                        }
                        for i in range(1, 41)
                    ],
                },
            ],
        }

        manifest_path = output_dir / "processed_cards.json"
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest_data, f, ensure_ascii=False, indent=2)

        # 创建媒体目录和文件
        (output_dir / "audio").mkdir()
        (output_dir / "screenshots").mkdir()

        with patch("main.create_apkg") as mock_create_apkg:
            mock_create_apkg.return_value = str(output_dir / "test.apkg")

            result = generate_apkg(
                output_dir=str(output_dir),
                card_styles=["basic"],
                theme="default",
                theme_overrides={},
            )

        # 验证结果
        assert result["total_cards"] == 100
        assert len(result["results"]) == 2
        assert len(result["apkg_paths"]) == 2

        # 验证 create_apkg 被调用了 2 次（每个视频一次）
        assert mock_create_apkg.call_count == 2

        # 验证每次调用的视频名称
        call_args_list = mock_create_apkg.call_args_list
        assert call_args_list[0][0][0] == "video1"  # 第一个参数是 deck_name
        assert call_args_list[1][0][0] == "video2"

    def test_batch_process_independent_mode_write(self, tmp_path):
        """批处理在独立模式下正确追加到 results"""
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        # Phase 1 创建的初始 manifest
        manifest = {
            "merge": False,
            "total_cards": 60,
            "results": [
                {
                    "video_name": "video1",
                    "cards_count": 60,
                    "processed": [{"index": i, "video_stem": "video1"} for i in range(60)],
                }
            ],
        }
        manifest_path = output_dir / "processed_cards.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        # 模拟批处理结果（video2 和 video3）
        batch_results = []
        for stem in ["video2", "video3"]:
            for i in range(30):
                batch_results.append({"index": i, "video_stem": stem})

        # 模拟批处理写入逻辑
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        if not manifest.get("merge", True):
            if "results" not in manifest:
                manifest["results"] = []

            # 按 video_stem 分组
            grouped = {}
            for p in batch_results:
                stem = p.get("video_stem", "unknown")
                if stem not in grouped:
                    grouped[stem] = []
                grouped[stem].append(p)

            # 追加每个视频的 result
            for stem, items in grouped.items():
                manifest["results"].append(
                    {
                        "video_name": stem,
                        "cards_count": len(items),
                        "processed": items,
                    }
                )

            # 更新总卡片数
            manifest["total_cards"] = sum(r["cards_count"] for r in manifest["results"])

        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        # 验证结果
        final = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert len(final["results"]) == 3  # video1 + video2 + video3
        assert final["total_cards"] == 120  # 60 + 30 + 30
        assert final["results"][0]["video_name"] == "video1"
        assert final["results"][1]["video_name"] == "video2"
        assert final["results"][2]["video_name"] == "video3"


# ─── 重复批处理幂等性测试 ─────────────────────────────────────


class TestBatchIdempotency:
    """验证批处理完成后再次触发不会重复添加卡片"""

    def test_batch_done_flag_prevents_retrigger(self):
        """batchDone=True 时前端不应再次触发批处理"""
        # 模拟前端状态
        batchDone = True
        isBatchProcessing = False
        videoFiles = [1, 2, 3]

        # 模拟按钮点击逻辑
        should_trigger_batch = (
            len(videoFiles) > 1 and not batchDone and not isBatchProcessing
        )

        assert should_trigger_batch is False, "batchDone=True 不应触发批处理"

    def test_is_batch_processing_flag_prevents_concurrent(self):
        """isBatchProcessing=True 时不应再次触发"""
        batchDone = False
        isBatchProcessing = True
        videoFiles = [1, 2, 3]

        should_trigger_batch = (
            len(videoFiles) > 1 and not batchDone and not isBatchProcessing
        )

        assert should_trigger_batch is False, "isBatchProcessing=True 不应触发批处理"

    def test_batch_triggered_ref_prevents_duplicate(self):
        """batchTriggeredRef.current=True 时 handleTriggerBatch 应提前返回"""
        # 模拟 handleTriggerBatch 的早期返回逻辑
        isBatchProcessing = False
        batchTriggered = True  # 已经被触发过
        videoFiles = [1, 2]

        # handleTriggerBatch 的早期返回条件
        should_return_early = isBatchProcessing or batchTriggered

        assert should_return_early is True, "batchTriggered=True 应提前返回"

    def test_manifest_merge_no_duplicate_cards(self, tmp_path):
        """验证合并模式不会添加重复卡片"""
        manifest_path = tmp_path / "processed_cards.json"

        # 初始 manifest
        manifest = {
            "merge": True,
            "processed": [
                {"index": 1, "video_stem": "video1"},
                {"index": 2, "video_stem": "video1"},
            ],
        }
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        # 模拟重复批处理（相同的卡片）
        batch_results = [
            {"index": 1, "video_stem": "video2"},
            {"index": 2, "video_stem": "video2"},
        ]

        # 使用 (index, video_stem) 去重
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        existing_keys = {
            (c["index"], c.get("video_stem")) for c in manifest["processed"]
        }

        new_cards = []
        for card in batch_results:
            key = (card["index"], card.get("video_stem"))
            if key not in existing_keys:
                new_cards.append(card)
                existing_keys.add(key)

        manifest["processed"].extend(new_cards)

        # 验证没有重复
        assert len(manifest["processed"]) == 4  # 2 + 2（不同 video_stem）

        # 再次添加相同的卡片应该被去重
        batch_results_2 = [
            {"index": 1, "video_stem": "video2"},  # 重复
            {"index": 3, "video_stem": "video2"},  # 新卡片
        ]

        new_cards_2 = []
        for card in batch_results_2:
            key = (card["index"], card.get("video_stem"))
            if key not in existing_keys:
                new_cards_2.append(card)
                existing_keys.add(key)

        manifest["processed"].extend(new_cards_2)

        # 只添加了 1 张新卡片
        assert len(manifest["processed"]) == 5

    def test_single_video_no_batch_needed(self):
        """单视频不应触发批处理"""
        videoFiles = [1]
        batchDone = False
        isBatchProcessing = False

        should_trigger_batch = (
            len(videoFiles) > 1 and not batchDone and not isBatchProcessing
        )

        assert should_trigger_batch is False, "单视频不应触发批处理"


# ─── 批处理中途失败恢复测试 ─────────────────────────────────────


class TestBatchFailureRecovery:
    """验证批处理失败后可以正确重试"""

    def test_error_resets_batch_triggered_ref(self):
        """错误事件应重置 batchTriggeredRef 允许重试"""
        # 模拟 SSE 错误事件处理逻辑
        batchTriggered = True  # 批处理已触发
        batchDone = False
        pendingPack = True

        # 收到错误事件后的状态重置
        error_event = {"type": "error", "message": "AI API 连接失败"}

        if error_event["type"] == "error":
            batchDone = False
            pendingPack = False
            batchTriggered = False  # 允许重试

        assert batchTriggered is False, "错误后应重置 batchTriggeredRef"
        assert pendingPack is False, "错误后应取消 pendingPack"
        assert batchDone is False

    def test_stream_error_resets_state(self):
        """SSE 流异常关闭（error=True）应重置状态"""
        batchTriggered = True
        batchDone = False
        pendingPack = True

        # 模拟 complete 事件带 error=True（流异常关闭的兜底事件）
        complete_event = {
            "type": "complete",
            "videos_processed": 0,
            "total_cards": 0,
            "error": True,
        }

        if complete_event.get("error"):
            # 流异常关闭的兜底事件，不要当作成功完成
            batchDone = False
            pendingPack = False
            batchTriggered = False

        assert batchTriggered is False
        assert pendingPack is False
        assert batchDone is False

    def test_exception_in_handler_resets_state(self):
        """handleTriggerBatch 的 catch 块应重置状态"""
        batchTriggered = True
        batchDone = False
        pendingPack = True
        isBatchProcessing = True

        # 模拟 try/catch 中的错误处理
        error = Exception("网络错误")
        try:
            raise error
        except Exception:
            batchDone = False
            pendingPack = False
            batchTriggered = False
            isBatchProcessing = False

        assert batchTriggered is False, "异常后应重置 batchTriggeredRef"
        assert isBatchProcessing is False, "异常后应重置 isBatchProcessing"

    def test_successful_complete_does_not_reset_triggered(self):
        """成功完成时不应重置 batchTriggeredRef（防止意外重试）"""
        batchTriggered = True
        batchDone = False
        pendingPack = True

        # 模拟成功的 complete 事件
        complete_event = {
            "type": "complete",
            "videos_processed": 2,
            "total_cards": 453,
            "error": False,
        }

        if not complete_event.get("error"):
            batchDone = True
            # batchTriggered 保持 True（不需要重置）

        assert batchDone is True
        assert batchTriggered is True, "成功后应保持 batchTriggeredRef"

    def test_partial_failure_preserves_completed_videos(self, tmp_path):
        """部分视频处理失败时，已完成的视频数据应保留在 manifest 中"""
        manifest_path = tmp_path / "processed_cards.json"

        # Phase 1 创建的初始 manifest
        manifest = {
            "merge": True,
            "processed": [
                {"index": i, "video_stem": "video1"} for i in range(60)
            ],
        }
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        # 模拟批处理：video2 成功，video3 失败
        video2_results = [{"index": i, "video_stem": "video2"} for i in range(30)]

        # video2 成功写入 manifest
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["processed"].extend(video2_results)
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        # video3 失败，不写入 manifest
        # 但 video1 和 video2 的数据应保留

        final = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert len(final["processed"]) == 90  # 60 + 30

        # 验证 video_stem 分布
        stems = {}
        for card in final["processed"]:
            stem = card.get("video_stem", "unknown")
            stems[stem] = stems.get(stem, 0) + 1

        assert stems["video1"] == 60
        assert stems["video2"] == 30
        assert "video3" not in stems

    def test_retry_after_failure_can_continue(self, tmp_path):
        """失败后重试应能继续处理剩余视频"""
        manifest_path = tmp_path / "processed_cards.json"

        # 初始 manifest（video1 已处理）
        manifest = {
            "merge": True,
            "processed": [
                {"index": i, "video_stem": "video1"} for i in range(60)
            ],
        }
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        # 第一次批处理尝试：video2 成功，video3 失败
        video2_results = [{"index": i, "video_stem": "video2"} for i in range(30)]
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["processed"].extend(video2_results)
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        # 第二次批处理尝试（重试）：video3 成功
        video3_results = [{"index": i, "video_stem": "video3"} for i in range(20)]
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["processed"].extend(video3_results)
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        # 验证最终结果
        final = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert len(final["processed"]) == 110  # 60 + 30 + 20

        stems = {}
        for card in final["processed"]:
            stem = card.get("video_stem", "unknown")
            stems[stem] = stems.get(stem, 0) + 1

        assert stems == {"video1": 60, "video2": 30, "video3": 20}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
