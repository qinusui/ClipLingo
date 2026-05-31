"""Tests for prompts module — build_screening_prompt and build_annotation_prompt."""

import sys
from pathlib import Path

import pytest

TEST_ROOT = Path(__file__).resolve().parent.parent.parent
BACKEND_DIR = TEST_ROOT / "backend"
sys.path.insert(0, str(TEST_ROOT))
sys.path.insert(0, str(BACKEND_DIR))

from api.prompts import (
    build_screening_prompt,
    build_annotation_prompt,
    build_system_prompt,
)


# ─── Test 1: screening prompt includes source language name ───


def test_screening_prompt_includes_source_language():
    """build_screening_prompt replaces {source_language} with display name."""
    prompt = build_screening_prompt(source_language="en", target_language="zh")
    assert "英语" in prompt   # get_name("en") → "英语"


# ─── Test 2: annotation prompt uses both languages ───


def test_annotation_prompt_uses_both_languages():
    """build_annotation_prompt substitutes both source and target language names."""
    prompt = build_annotation_prompt("grammar", source_language="ja", target_language="ko")
    assert "日语" in prompt
    assert "韩语" in prompt


# ─── Test 3: custom prompt overrides default criteria ───


def test_screening_custom_replaces_default_criteria():
    """When custom_prompt is provided, it replaces the default criteria entirely."""
    prompt = build_screening_prompt(custom_prompt="My custom criteria", source_language="en")
    assert "My custom criteria" in prompt
    assert "语法知识点" not in prompt   # default criteria removed


# ─── Test 4: correct_text adds extra field instruction ───


def test_screening_correct_text_adds_field_instruction():
    """correct_text=True appends corrected_text guidance to return format."""
    plain = build_screening_prompt(source_language="en")
    with_correct = build_screening_prompt(source_language="en", correct_text=True)
    assert "corrected_text" not in plain
    assert "corrected_text" in with_correct


# ─── Test 5: annotation purpose selects grammar vs vocab template ───


def test_annotation_prompt_vocabulary_differs_from_grammar():
    """vocab purpose produces notes format different from grammar."""
    grammar = build_annotation_prompt("grammar")
    vocab = build_annotation_prompt("vocab")
    assert "语法知识点和实用表达" in grammar
    assert "重点单词-词性-释义" in vocab


# ─── Test 6: custom annotation criteria ───


def test_annotation_custom_criteria_overrides():
    """Custom annotation criteria replaces the built-in template."""
    prompt = build_annotation_prompt("grammar", custom_criteria="Custom rules here")
    assert "Custom rules here" in prompt
    assert "学习教材编写专家" not in prompt  # default persona removed


# ─── Test 7: system prompt (legacy full-recommend mode) ───


def test_build_system_prompt_formats_both_languages():
    """Legacy build_system_prompt formats source/target language into template."""
    prompt = build_system_prompt(source_language="fr", target_language="de")
    assert "法语" in prompt
    assert "德语" in prompt
