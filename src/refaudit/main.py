import argparse
import os
import pathlib
import sys

from . import __version__


def write_stdout(text: str) -> None:
    """Write to stdout, tolerating consoles that cannot encode every character.

    Reports embed emoji (🚩 / ❌) and references carry arbitrary Unicode, both of
    which raise UnicodeEncodeError on legacy codepages such as Windows cp932.
    Fall back to the console's own encoding with replacement characters so that
    Japanese text still renders and only the unencodable glyphs degrade to '?'.
    """
    try:
        sys.stdout.write(text)
        return
    except UnicodeEncodeError:
        pass

    buffer = getattr(sys.stdout, "buffer", None)
    if buffer is None:
        # Stream without a byte layer (e.g. captured stdout): degrade in-place.
        sys.stdout.write(text.encode("ascii", errors="replace").decode("ascii"))
        return

    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    buffer.write(text.encode(encoding, errors="replace"))
    buffer.flush()


def run(
    text: str,
    out_path: pathlib.Path | None,
    show_all: bool = False,
    debug: bool = False,
    force_pdf: bool | None = None,
    show_clean: bool = False,
) -> int:
    from .parser import split_references

    refs = split_references(text, force_pdf=force_pdf)

    # --show-clean: 再構成した文献リストを stdout に出して終了（API照合なし）。
    if show_clean:
        body = "".join(f"{i}. {ref}\n" for i, ref in enumerate(refs, 1))
        write_stdout(body)
        return 0

    from .crossref import CrossrefClient
    from .report import make_markdown_bad_only, make_markdown_full

    client = CrossrefClient(debug=debug, email=os.getenv("CONTACT_EMAIL"))
    results = [client.check_one(line) for line in refs]
    md = make_markdown_full(results) if show_all else make_markdown_bad_only(results)
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(md, encoding="utf-8")
    else:
        write_stdout(md)
    return 0


def main() -> None:
    p = argparse.ArgumentParser(
        prog="citeguard",
        description="Audit references via Crossref, PubMed, and arXiv. Detect missing or retracted citations.",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    input_group = p.add_mutually_exclusive_group()
    input_group.add_argument("--text", help="Inline pasted references text.", default=None)
    input_group.add_argument(
        "--input-file", type=pathlib.Path,
        help="Path to a file containing references (one per line).", default=None,
    )

    p.add_argument("--out", help="Path to Markdown report. If omitted, print to stdout.", default=None)
    p.add_argument("--all", action="store_true", help="Include all references (not just problems).")
    p.add_argument("--debug", action="store_true", help="Show Crossref candidates for unmatched refs.")
    p.add_argument(
        "--pdf", dest="force_pdf", action="store_true", default=None,
        help="Force line-numbered PDF cleaning (footers, marginal line numbers).",
    )
    p.add_argument(
        "--no-pdf", dest="force_pdf", action="store_false",
        help="Disable automatic PDF cleaning detection.",
    )
    p.add_argument(
        "--show-clean", action="store_true",
        help="Print the reconstructed reference list to stdout and exit (no API calls).",
    )
    p.add_argument(
        "--email",
        help="Contact email for API etiquette (Crossref/PubMed). "
             "Alternatively set CONTACT_EMAIL env var or .env file.",
        default=None,
    )
    args = p.parse_args()

    if args.email:
        os.environ["CONTACT_EMAIL"] = args.email

    if args.text is not None:
        text = args.text
    elif args.input_file is not None:
        text = args.input_file.read_text(encoding="utf-8")
    else:
        if sys.stdin.isatty():
            p.print_usage(sys.stderr)
            print("error: provide --text, --input-file, or pipe text via stdin", file=sys.stderr)
            sys.exit(2)
        text = sys.stdin.read()

    out = pathlib.Path(args.out) if args.out else None
    sys.exit(run(
        text, out,
        show_all=args.all,
        debug=args.debug,
        force_pdf=args.force_pdf,
        show_clean=args.show_clean,
    ))


if __name__ == "__main__":
    main()
