import argparse
import pathlib
import sys

from .crossref import CrossrefClient
from .parser import split_references
from .report import make_markdown_bad_only


def run(text: str, out_path: pathlib.Path) -> int:
    client = CrossrefClient()
    refs = split_references(text)
    results = [client.check_one(line) for line in refs]
    md = make_markdown_bad_only(results)
    out_path.write_text(md, encoding="utf-8")
    return 0


def main() -> None:
    p = argparse.ArgumentParser(
        description="Audit references via Crossref and output bad ones as Markdown."
    )
    p.add_argument("--text", help="Inline pasted references text. If omitted, read from STDIN.", default=None)
    p.add_argument("--out", help="Path to Markdown report", default="outputs/report.md")
    args = p.parse_args()

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    if args.text is not None:
        text = args.text
    else:
        text = sys.stdin.read()

    sys.exit(run(text, out))


if __name__ == "__main__":
    main()

