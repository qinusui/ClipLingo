"""
测试 BcutASREngine — 必剪云端语音识别
"""
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock, ANY

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.asr.bcut_engine import BcutASREngine


class TestBcutAPI:
    """API 请求格式和响应解析"""

    def test_upload_request_format(self):
        """上传第一步 POST body 格式应正确"""
        engine = BcutASREngine()
        session = MagicMock()

        upload_resp = MagicMock()
        upload_resp.json.return_value = {"data": {
            "upload_urls": ["http://up1"],
            "per_size": 512,
            "in_boss_key": "boss1",
            "resource_id": "res1",
            "upload_id": "up1",
        }}
        session.post.return_value = upload_resp
        session.put.return_value = MagicMock(headers={"Etag": '"etag1"'})

        commit_resp = MagicMock()
        commit_resp.json.return_value = {"data": {"download_url": "http://dl"}}
        session.post.side_effect = [upload_resp, commit_resp]

        result = engine._upload(session, b"test audio data")
        assert result == "http://dl"
        # 验证第一次 POST 的 body 格式
        first_call_args = session.post.call_args_list[0]
        sent_body = first_call_args[1]["data"]
        assert '"type": 2' in sent_body
        assert '"model_id": "8"' in sent_body

    def test_parse_result_sentence_mode(self):
        """句子模式应解析为 start/end/text 格式（时间戳为毫秒）"""
        engine = BcutASREngine(need_word_time_stamp=False)
        resp = {
            "utterances": [
                {"transcript": "Hello world", "start_time": 1000, "end_time": 3000},
                {"transcript": "Goodbye", "start_time": 4000, "end_time": 5000},
            ]
        }
        result = engine._parse_result(resp)
        assert len(result) == 2
        assert result[0] == {"start": 1.0, "end": 3.0, "text": "Hello world"}
        assert result[1] == {"start": 4.0, "end": 5.0, "text": "Goodbye"}

    def test_parse_result_word_mode(self):
        """词级时间戳模式应展开每个 utterance 的 words"""
        engine = BcutASREngine(need_word_time_stamp=True)
        resp = {
            "utterances": [
                {"words": [
                    {"label": "Hello", "start_time": 1000, "end_time": 1500},
                    {"label": "world", "start_time": 1500, "end_time": 2000},
                ]}
            ]
        }
        result = engine._parse_result(resp)
        assert len(result) == 2
        assert result[0]["text"] == "Hello"
        assert result[1]["text"] == "world"

    def test_parse_result_empty_text_filtered(self):
        """空白文本应被过滤"""
        engine = BcutASREngine()
        resp = {
            "utterances": [
                {"transcript": "   ", "start_time": 0, "end_time": 1000},
                {"transcript": "Valid text", "start_time": 2000, "end_time": 3000},
            ]
        }
        result = engine._parse_result(resp)
        assert len(result) == 1
        assert result[0]["text"] == "Valid text"

    def test_poll_result_state_4_returns(self):
        """state == 4 时应返回解析后的 result"""
        engine = BcutASREngine()
        session = MagicMock()

        call_count = [0]

        def fake_get(*args, **kwargs):
            call_count[0] += 1
            resp = MagicMock()
            if call_count[0] >= 3:
                resp.json.return_value = {
                    "data": {
                        "state": 4,
                        "result": json.dumps({"utterances": [
                            {"transcript": "Done", "start_time": 0, "end_time": 1000}
                        ]}),
                    }
                }
            else:
                resp.json.return_value = {"data": {"state": 1}}
            return resp

        session.get.side_effect = fake_get

        result = engine._poll_result(session, "task123")
        assert len(result["utterances"]) == 1

    def test_poll_result_timeout_raises(self):
        """超过 500 次轮询应抛出 RuntimeError"""
        engine = BcutASREngine()
        session = MagicMock()
        resp = MagicMock()
        resp.json.return_value = {"data": {"state": 1}}  # 永不完成
        session.get.return_value = resp

        with patch("time.sleep", return_value=None):  # 跳过 sleep
            try:
                engine._poll_result(session, "task123")
                assert False, "应抛出异常"
            except RuntimeError as e:
                assert "超时" in str(e)


class TestBcutCache:
    """缓存和限流"""

    def test_cache_hit_returns_cached(self):
        """CRC32 匹配时命中缓存，不发起网络请求"""
        import zlib
        import os

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(b"fake audio data for cache test")
            tmp_path = f.name

        try:
            crc32_hex = format(zlib.crc32(b"fake audio data for cache test") & 0xFFFFFFFF, "08x")
            fake_cache = MagicMock()
            fake_cache.get.return_value = [{"start": 0.0, "end": 1.0, "text": "cached"}]

            with patch("core.asr.bcut_engine._get_diskcache", return_value=fake_cache):
                engine = BcutASREngine()
                result = engine.transcribe(tmp_path)
                assert len(result) == 1
                assert result[0]["text"] == "cached"
        finally:
            os.unlink(tmp_path)

    def test_rate_limit_call_count_exceeded(self):
        """超过 100 次调用时限流报错"""
        cache = MagicMock()
        # 模拟已存在 100 条记录
        cache._sql.return_value.fetchall.return_value = [(f"key{i}",) for i in range(100)]
        cache.get.return_value = 30.0  # 每条 30 秒

        engine = BcutASREngine()
        try:
            engine._check_rate_limit(cache, 60.0)
            assert False, "应抛出异常"
        except RuntimeError as e:
            assert "100" in str(e)

    def test_rate_limit_duration_exceeded(self):
        """超过 360 分钟时限流报错"""
        cache = MagicMock()
        cache._sql.return_value.fetchall.return_value = [(f"key{i}",) for i in range(10)]
        # 10 条记录 × 35 分钟 = 350 分钟，加当前 11 分钟 = 361 → 超限
        cache.get.side_effect = [35.0 * 60] * 10

        engine = BcutASREngine()
        try:
            engine._check_rate_limit(cache, 11.0 * 60)
            assert False, "应抛出异常"
        except RuntimeError as e:
            assert "360" in str(e)

    def test_rate_limit_sql_error_no_block(self):
        """缓存 SQL 查询出错时不应阻塞流程"""
        cache = MagicMock()
        cache._sql.side_effect = Exception("SQL error")

        engine = BcutASREngine()
        # 不应抛出异常
        engine._check_rate_limit(cache, 60.0)


class TestBcutFullFlow:
    """完整流程（Mock 网络）"""

    def test_full_transcribe_flow(self):
        """完整的 transcribe 流程：上传→创建任务→轮询→解析→缓存"""
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(b"test audio data")
            tmp_path = f.name

        import os
        try:
            fake_cache = MagicMock()
            fake_cache.get.return_value = None  # 无缓存
            fake_cache._sql.return_value.fetchall.return_value = []  # 无限流记录

            session = MagicMock()

            # Step 1: 上传授权
            upload_resp = MagicMock()
            upload_resp.json.return_value = {"data": {
                "upload_urls": ["http://up1"],
                "per_size": 1024,
                "in_boss_key": "boss1",
                "resource_id": "res1",
                "upload_id": "up1",
            }}

            # Step 2: 分片 PUT
            put_resp = MagicMock()
            put_resp.headers = {"Etag": '"etag1"'}

            # Step 3: 提交上传
            commit_resp = MagicMock()
            commit_resp.json.return_value = {"data": {"download_url": "http://dl"}}

            # Step 4: 创建任务
            task_resp = MagicMock()
            task_resp.json.return_value = {"data": {"task_id": "task123"}}

            session.post.side_effect = [upload_resp, commit_resp, task_resp]
            session.put.return_value = put_resp

            # 轮询结果
            poll_resp = MagicMock()
            poll_resp.json.return_value = {"data": {
                "state": 4,
                "result": json.dumps({"utterances": [
                    {"transcript": "Test", "start_time": 0, "end_time": 2000}
                ]}),
            }}
            session.get.return_value = poll_resp

            with (
                patch("core.asr.bcut_engine._get_diskcache", return_value=fake_cache),
                patch("requests.Session", return_value=session),
                patch.object(BcutASREngine, "_get_audio_duration", return_value=30.0),
            ):
                engine = BcutASREngine()
                result = engine.transcribe(tmp_path)

                assert len(result) == 1
                assert result[0]["text"] == "Test"
                assert result[0]["start"] == 0.0
                assert result[0]["end"] == 2.0
                # 确认结果缓存已写入（第二次 set 调用）
                assert fake_cache.set.call_count >= 2
                # 第二次 set 是结果缓存
                last_call_args = fake_cache.set.call_args_list[1]
                assert last_call_args[0][0].startswith("BcutASREngine:")
        finally:
            os.unlink(tmp_path)


class TestBcutAvailability:
    """可用性检查"""

    def test_bcut_is_available(self):
        """Bcut 引擎永远可用（纯 HTTP API）"""
        assert BcutASREngine.is_available() is True
