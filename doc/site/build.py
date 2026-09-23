#!/usr/bin/env python3
"""Builds site/src/content/docs/ (an Astro + Starlight site, published to
GitHub Pages) from doc/manual/*.md -- the exact same single source `phosphor
help` (in the deck) and `phosphor docs` (AGENTS.md, for AI assistants)
already read. A third reader, not a second copy: never edit the generated
pages by hand, edit the manual and run this again.

    python3 doc/site/build.py

This script only turns each manual page into a page Starlight understands
(front matter, image paths rewritten to be site-root-relative) and copies
doc/img alongside it as a public asset. The actual site (nav, search, theme,
the terminal-framed code blocks) is site/'s own Astro + Starlight build:

    cd site && npm install && npm run build

CI runs both steps (see .github/workflows/pages.yml).
"""
import os, re, shutil, sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "lib"))
import docs  # noqa: E402  (ORDER, page(): the same manual reader phosphor docs uses)

SITE = os.path.join(REPO, "site")
# doc/img is copied into site/src/assets/img (not public/img): a path
# relative to a content file there, not a site-root-absolute one, is what
# lets Astro's own image pipeline find, optimize and correctly base-prefix
# it (astro.config.mjs sets `base: '/phosphor-deck'`; a literal `/img/...`
# in markdown skips that prefix -- only Vite-processed asset imports get
# it -- and 404s once deployed; a *relative* path with no leading "/",
# on the other hand, only resolves if Astro can actually locate a real
# file there, which public/ assets aren't). A manual page's source sits at
# src/content/docs/manual/NAME.md, three levels above src/ -- so
# `../img/x.png` (doc/manual's own path, one level up to doc/) becomes
# `../../../assets/img/x.png` here.
IMG_LINK = re.compile(r"\(\.\./img/")

TOPIC_TITLES = {
    "concepts": "Concepts", "install": "Install", "patterns": "Patterns",
    "profile": "The profile", "commands": "Commands", "keys": "Keys",
    "phones": "Screens", "workspaces": "Workspaces", "mentions": "Mentions",
    "web": "The deck in a browser", "tunnels": "Tunnels", "clipboard": "Clipboard",
    "privacy": "Privacy", "troubleshooting": "Troubleshooting",
}


def front_matter(title, order):
    return "---\ntitle: %s\nsidebar:\n  order: %d\n---\n\n" % (title, order)


def convert_body(md):
    """../img/x.png (doc/manual's own relative path) -> a path relative to
    site/src/content/docs/manual/, where Astro's image pipeline can find
    what copy_images() below puts at site/src/assets/img/ (see IMG_LINK)."""
    return IMG_LINK.sub("(../../../assets/img/", md)


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def build_index():
    readme = open(os.path.join(docs.MAN, "README.md")).read()
    # The topic table is the manual's own index -- reuse it instead of a
    # second, hand-kept list of what the manual covers.
    table = readme.split("| topic | what it covers |", 1)[1]
    table = "| topic | what it covers |" + table.split("\n\n", 1)[0]
    topic_alt = "|".join(re.escape(n) for n in docs.ORDER)
    # Relative, not site-root-absolute (this page is the site root itself):
    # see the note on IMG_LINK above -- a literal leading "/" here would
    # skip astro.config.mjs's `base` and 404 once deployed.
    table = re.sub(r"^\| (%s) \|" % topic_alt,
                    lambda m: "| [%s](manual/%s/) |" % (m.group(1), m.group(1)), table, flags=re.M)
    body = (
        "---\n"
        "title: Phosphor Deck\n"
        "description: One terminal session as your whole command room.\n"
        "template: splash\n"
        "hero:\n"
        "  tagline: One terminal session (zellij) as your whole command room --\n"
        "    your machines, your notebook, your chat, from any screen.\n"
        "  image:\n"
        "    file: ../../assets/logo.svg\n"
        "  actions:\n"
        "    - text: Read the manual\n"
        "      link: manual/concepts/\n"
        "      icon: right-arrow\n"
        "    - text: GitHub\n"
        "      link: https://github.com/rsmedrano-cloud/phosphor-deck\n"
        "      icon: external\n"
        "      variant: minimal\n"
        "---\n\n"
        "## Install\n\n"
        "On the machine that will be the brain:\n\n"
        "```sh\n"
        "sh install.sh\n"
        "```\n\n"
        "No root, no dependencies beyond a POSIX shell: it downloads zellij,\n"
        "yazi, btop, gping, ctop and rclone into `~/.local/bin` and asks\n"
        '"set it up now?" -- see [install](manual/install/) for what it does by hand.\n\n'
        "## Manual\n\n" + table + "\n"
    )
    write(os.path.join(SITE, "src", "content", "docs", "index.md"), body)


def build_pages():
    out = os.path.join(SITE, "src", "content", "docs", "manual")
    for i, name in enumerate(docs.ORDER, start=1):
        md = docs.page(name)
        md = re.sub(r"^# .+\n", "", md, count=1)  # the title becomes front matter's title instead
        body = convert_body(md)
        write(os.path.join(out, name + ".md"), front_matter(TOPIC_TITLES[name], i) + body)


def copy_images():
    src = os.path.join(REPO, "doc", "img")
    dst = os.path.join(SITE, "src", "assets", "img")
    if os.path.exists(dst):
        shutil.rmtree(dst)
    if os.path.exists(src):
        shutil.copytree(src, dst)


def copy_logo():
    """The hero image and the sidebar/nav logo Starlight's own config
    (site/astro.config.mjs) points at -- copied, not symlinked, so `npm run
    build` needs nothing outside site/ once this script has run."""
    src = os.path.join(REPO, "doc", "img", "logo", "logo.svg")
    dst = os.path.join(SITE, "src", "assets", "logo.svg")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy(src, dst)


def main():
    docs_dir = os.path.join(SITE, "src", "content", "docs")
    if os.path.exists(docs_dir):
        shutil.rmtree(docs_dir)
    os.makedirs(docs_dir)
    build_index()
    build_pages()
    copy_images()
    copy_logo()
    print("site/src/content/docs/ built: %d manual pages + index" % len(docs.ORDER))


if __name__ == "__main__":
    main()
