#!/usr/bin/env python3
"""Builds docs/ (a GitHub Pages site) from doc/manual/*.md -- the exact same
single source `phosphor help` (in the deck) and `phosphor docs` (AGENTS.md,
for AI assistants) already read. A third reader, not a second copy: never
edit docs/ by hand, edit the manual and run this again.

    python3 doc/site/build.py

Needs nothing beyond the standard library: GitHub Pages' own Jekyll build
does the actual rendering (theme: jekyll-theme-hacker, in docs/_config.yml,
one of GitHub's built-in supported themes -- no Gemfile, no Node, no
Actions workflow to build it). This script only turns each manual page
into a page Jekyll understands (front matter, image paths rewritten to be
site-root-relative) and copies doc/img alongside it.
"""
import os, re, shutil, sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "lib"))
import docs  # noqa: E402  (ORDER, page(): the same manual reader phosphor docs uses)

OUT = os.path.join(REPO, "docs")
IMG_LINK = re.compile(r"\(\.\./img/")

TOPIC_TITLES = {
    "concepts": "Concepts", "install": "Install", "patterns": "Patterns",
    "profile": "The profile", "commands": "Commands", "keys": "Keys",
    "phones": "Screens", "workspaces": "Workspaces", "mentions": "Mentions",
    "web": "The deck in a browser", "tunnels": "Tunnels", "clipboard": "Clipboard",
    "privacy": "Privacy", "troubleshooting": "Troubleshooting",
}


def front_matter(title, permalink=""):
    return "---\nlayout: default\ntitle: %s\npermalink: /%s\n---\n\n" % (title, permalink)


def convert_body(md):
    """../img/x.png (doc/manual's own relative path) -> /img/x.png (site-root
    relative: doc/img is copied to docs/img by main() below)."""
    return IMG_LINK.sub("(/img/", md)


def nav_line(current):
    def one(name):
        return ("**%s**" % TOPIC_TITLES[name]) if name == current else \
               ("[%s](/%s/)" % (TOPIC_TITLES[name], name))
    return "[Home](/) · " + " · ".join(one(name) for name in docs.ORDER) + "\n\n---\n\n"


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
    table = re.sub(r"^\| (%s) \|" % topic_alt,
                    lambda m: "| [%s](/%s/) |" % (m.group(1), m.group(1)), table, flags=re.M)
    body = (
        "Phosphor Deck: one terminal session (zellij) as your whole command "
        "room -- your machines, your notebook, your chat, from any screen. "
        "[Source and README](https://github.com/rsmedrano-cloud/phosphor-deck).\n\n"
        "## Manual\n\n" + table + "\n"
    )
    write(os.path.join(OUT, "index.md"), front_matter("Phosphor Deck") + body)


def build_pages():
    for name in docs.ORDER:
        md = docs.page(name)
        md = re.sub(r"^# .+\n", "", md, count=1)  # the title becomes front matter's title instead
        body = nav_line(name) + convert_body(md)
        write(os.path.join(OUT, name + ".md"), front_matter(TOPIC_TITLES[name], name + "/") + body)


def build_config():
    write(os.path.join(OUT, "_config.yml"),
          'theme: jekyll-theme-hacker\n'
          'title: Phosphor Deck\n'
          'description: "One terminal session as your whole command room"\n'
          'show_downloads: false\n')


def copy_images():
    src = os.path.join(REPO, "doc", "img")
    dst = os.path.join(OUT, "img")
    if os.path.exists(dst):
        shutil.rmtree(dst)
    if os.path.exists(src):
        shutil.copytree(src, dst)


def copy_static():
    """favicon.ico, apple-touch-icon.png: dropped at the site root, where
    every browser looks for them by convention -- jekyll-theme-hacker has
    no head-injection point to <link> them explicitly, so this is simpler
    and just as reliable."""
    src = os.path.join(HERE, "static")
    if not os.path.isdir(src):
        return
    for name in os.listdir(src):
        shutil.copy(os.path.join(src, name), os.path.join(OUT, name))


def main():
    if os.path.exists(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT)
    build_config()
    build_index()
    build_pages()
    copy_images()
    copy_static()
    print("docs/ built: %d pages + index" % len(docs.ORDER))


if __name__ == "__main__":
    main()
