"""レガシーコードページのコンソールへの stdout 出力テスト。

日本語 Windows の既定コンソールは cp932 で、レポート中の絵文字（🚩 / ❌）を
エンコードできず UnicodeEncodeError で落ちていた。write_stdout() は
コンソール自身のエンコーディングで置換文字にフォールバックするため、
日本語はそのまま読め、絵文字だけが '?' に落ちる。
"""

from __future__ import annotations

import io

from refaudit.main import write_stdout


def _cp932_stdout() -> io.TextIOWrapper:
    """cp932 コンソールを模した stdout（buffer 付き）を返す。"""
    return io.TextIOWrapper(io.BytesIO(), encoding="cp932", newline="")


def test_write_stdout_passes_through_encodable_text(monkeypatch):
    stream = _cp932_stdout()
    monkeypatch.setattr("sys.stdout", stream)

    write_stdout("正常な日本語テキスト\n")

    stream.flush()
    assert stream.buffer.getvalue().decode("cp932") == "正常な日本語テキスト\n"


def test_write_stdout_survives_unencodable_emoji(monkeypatch):
    stream = _cp932_stdout()
    monkeypatch.setattr("sys.stdout", stream)

    write_stdout("## 🚩 撤回・撤回相当（Crossref 更新通知）\n- 入力: ❌\n")

    stream.flush()
    out = stream.buffer.getvalue().decode("cp932")
    # 日本語部分は保持され、エンコード不能な絵文字だけが置換される。
    assert "撤回・撤回相当（Crossref 更新通知）" in out
    assert "入力:" in out
    assert "🚩" not in out
    assert "?" in out


def test_write_stdout_handles_stream_without_buffer(monkeypatch):
    class NoBufferStream(io.StringIO):
        encoding = "cp932"

        def write(self, s):
            s.encode(self.encoding)  # 実コンソール同様にエンコード失敗させる
            return super().write(s)

    stream = NoBufferStream()
    monkeypatch.setattr("sys.stdout", stream)

    write_stdout("🚩 retracted\n")

    assert "retracted" in stream.getvalue()
