#!/usr/bin/env python3
"""
Blog Engine - Static Site Generator
Example project for TempleDB
"""

import os
import sys
import re
import yaml
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any
import markdown
from jinja2 import Environment, FileSystemLoader

class BlogGenerator:
    """Simple static site generator for blogs"""

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.content_dir = base_dir / "content"
        self.template_dir = base_dir / "templates"
        self.static_dir = base_dir / "static"
        self.output_dir = base_dir / "output"

        # Initialize Jinja2
        self.jinja_env = Environment(loader=FileSystemLoader(str(self.template_dir)))

        # Markdown extensions
        self.md = markdown.Markdown(extensions=['meta', 'fenced_code', 'tables'])

    def parse_post(self, file_path: Path) -> Dict[str, Any]:
        """Parse a markdown post with frontmatter"""
        content = file_path.read_text()

        # Extract frontmatter
        frontmatter_pattern = r'^---\s*\n(.*?)\n---\s*\n'
        match = re.match(frontmatter_pattern, content, re.DOTALL)

        if match:
            frontmatter = yaml.safe_load(match.group(1))
            body = content[match.end():]
        else:
            frontmatter = {}
            body = content

        # Convert markdown to HTML
        html = self.md.convert(body)

        return {
            'title': frontmatter.get('title', 'Untitled'),
            'date': frontmatter.get('date', datetime.now().date()),
            'author': frontmatter.get('author', 'Anonymous'),
            'tags': frontmatter.get('tags', []),
            'slug': file_path.stem,
            'content': html,
            'file_path': file_path
        }

    def get_posts(self) -> List[Dict[str, Any]]:
        """Get all blog posts"""
        posts_dir = self.content_dir / "posts"
        posts = []

        if not posts_dir.exists():
            return posts

        for file_path in posts_dir.glob("*.md"):
            try:
                post = self.parse_post(file_path)
                posts.append(post)
            except Exception as e:
                print(f"Error parsing {file_path}: {e}", file=sys.stderr)

        # Sort by date (newest first)
        posts.sort(key=lambda p: p['date'], reverse=True)

        return posts

    def render_index(self, posts: List[Dict[str, Any]]):
        """Render the index page"""
        template = self.jinja_env.get_template('index.html')
        html = template.render(
            posts=posts,
            site_title=os.getenv('BLOG_TITLE', 'My Blog'),
            generated_at=datetime.now()
        )

        output_file = self.output_dir / "index.html"
        output_file.write_text(html)
        print(f"✅ Generated: index.html")

    def render_post(self, post: Dict[str, Any]):
        """Render a single post"""
        template = self.jinja_env.get_template('post.html')
        html = template.render(
            post=post,
            site_title=os.getenv('BLOG_TITLE', 'My Blog')
        )

        output_file = self.output_dir / f"{post['slug']}.html"
        output_file.write_text(html)
        print(f"✅ Generated: {post['slug']}.html")

    def copy_static(self):
        """Copy static files to output"""
        if not self.static_dir.exists():
            return

        import shutil
        output_static = self.output_dir / "static"
        if output_static.exists():
            shutil.rmtree(output_static)

        shutil.copytree(self.static_dir, output_static)
        print(f"✅ Copied static files")

    def generate(self):
        """Generate the entire site"""
        print(f"\n🏛️  TempleDB Blog Engine")
        print(f"📁 Source: {self.base_dir}")
        print(f"📝 Output: {self.output_dir}\n")

        # Create output directory
        self.output_dir.mkdir(exist_ok=True)

        # Get all posts
        posts = self.get_posts()
        print(f"📄 Found {len(posts)} posts")

        # Render pages
        self.render_index(posts)

        for post in posts:
            self.render_post(post)

        # Copy static files
        self.copy_static()

        print(f"\n✅ Site generated successfully!")
        print(f"📍 Open: {self.output_dir}/index.html\n")

def main():
    """Main entry point"""
    base_dir = Path(__file__).parent.parent

    generator = BlogGenerator(base_dir)
    generator.generate()

if __name__ == '__main__':
    main()
