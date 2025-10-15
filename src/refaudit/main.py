import argparse
import pathlib
import sys

from .crossref import CrossrefClient
from .parser import split_references
from .report import make_markdown_bad_only, make_markdown_full


def run(text: str, out_path: pathlib.Path, show_all: bool = False, debug: bool = False) -> int:
    client = CrossrefClient(debug=debug)
    refs = split_references(text)
    results = [client.check_one(line) for line in refs]
    md = make_markdown_full(results) if show_all else make_markdown_bad_only(results)
    out_path.write_text(md, encoding="utf-8")
    return 0


def main() -> None:
    p = argparse.ArgumentParser(
        description="Audit references via Crossref and output bad ones as Markdown."
    )
    p.add_argument("--text", help="Inline pasted references text. If omitted, read from STDIN.", default=None)
    p.add_argument("--out", help="Path to Markdown report", default="outputs/report.md")
    p.add_argument("--all", action="store_true", help="正常も含めたフル一覧を出力")
    p.add_argument("--debug", action="store_true", help="未発見時にCrossref候補(上位3)を併記")
    args = p.parse_args()

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    if args.text is not None:
        text = args.text
    else:
        text = sys.stdin.read()

    sys.exit(run(text, out, show_all=args.all, debug=args.debug))


if __name__ == "__main__":
    main()
