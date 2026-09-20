"""Composer's explicit-manifest adapter for Tufted Blog Template 9688c47b.

Python >=3.10, standard library only. Input is a snapshot; output must not exist.
No user hooks, PATH compiler lookup, clean command or automatic deployment.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import os
from datetime import datetime, timezone
from email.utils import format_datetime
import hashlib
from html import escape, unescape
from html.parser import HTMLParser
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit
import xml.etree.ElementTree as ET


def appearance(root):
    path = root / 'composer/site.json'
    value = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'schemaVersion': 1}
    if not isinstance(value, dict) or value.get('schemaVersion') != 1: raise ValueError('Unsupported appearance settings')
    schema = json.loads(Path(__file__).with_name('appearance-schema.json').read_text(encoding='utf-8'))
    def get(path, default=None):
        result = value
        for key in path.split('.'):
            if not isinstance(result, dict): raise ValueError('Invalid appearance group: ' + path)
            if key not in result: return default
            result = result[key]
        return result
    defaults, public_settings = {}, {'schemaVersion': 1}
    for group in schema:
        for field in group['fields']:
            key, kind = field['path'], field['type']; defaults[key] = field['default']; current = get(key)
            if current is None: continue
            if kind == 'number' and (type(current) not in (int, float) or not field['min'] <= current <= field['max']): raise ValueError('Invalid appearance number: ' + key)
            if kind == 'boolean' and not isinstance(current, bool): raise ValueError('Invalid appearance switch: ' + key)
            if kind == 'color' and (not isinstance(current, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', current)): raise ValueError('Invalid appearance color: ' + key)
            if kind == 'select' and current not in [option[0] for option in field['options']]: raise ValueError('Invalid appearance choice: ' + key)
            if kind == 'text' and (not isinstance(current, str) or len(current) > 300 or re.search(r'[\x00-\x1f]', current)): raise ValueError('Invalid appearance text: ' + key)
            if key.endswith('Font') and re.search(r'[;{}<>\\()]', str(current)): raise ValueError('Invalid font family list')
            group_value = public_settings
            keys = key.split('.')
            for part in keys[:-1]: group_value = group_value.setdefault(part, {})
            group_value[keys[-1]] = current
    def effective(key): return get(key, defaults[key])
    if effective('layout.textPercent') * (1 + (effective('layout.notePercent') + effective('layout.noteGap')) / 100) > 100: raise ValueError('Text and margin notes exceed website width')
    if effective('navigation.enabled') and effective('toc.enabled') and effective('navigation.side') == effective('toc.side'): raise ValueError('Section navigation and article TOC must use different sides')
    css = []
    variables = {'background': '--theme-bg', 'text': '--theme-text', 'heading': '--theme-heading', 'link': '--blog-link', 'codeBackground': '--theme-pre-bg', 'border': '--theme-table-border'}
    for theme in ['light', 'dark']:
        rules = [variable + ':' + get('colors.' + theme + '.' + key) for key, variable in variables.items() if get('colors.' + theme + '.' + key) is not None]
        if rules: css.append('html[data-theme="' + theme + '"]{' + ';'.join(rules) + '}')
    properties = {'type.bodyFont': ('body', 'font-family', ''), 'type.codeFont': ('pre,code', 'font-family', ''), 'type.baseSize': ('html', 'font-size', 'px'), 'type.lineHeight': ('article p,article li', 'line-height', ''), 'type.paragraphGap': ('article p', 'margin-bottom', 'rem'), 'layout.maxWidth': (':root', '--blog-max-width', 'px')}
    for key, (selector, prop, unit) in properties.items():
        if get(key) is not None: css.append(selector + '{' + prop + ':' + str(get(key)) + unit + '}')
    css.append('article a:any-link{color:var(--blog-link,inherit)}')
    css.append('.blog-button{display:inline-block;padding:.45em .8em;border-radius:.3em;text-decoration:none;background-image:none!important}.blog-button-filled{background:var(--theme-text);color:var(--theme-bg)!important}.blog-button-outline{border:1px solid currentColor}.blog-button:focus-visible{outline:2px solid currentColor;outline-offset:3px}')
    percent,note,gap=effective('layout.textPercent'),effective('layout.notePercent'),effective('layout.noteGap')
    rails={'left':0,'right':0}
    if effective('toc.enabled'): rails[effective('toc.side')]=effective('toc.width')+32
    if effective('navigation.enabled'): rails[effective('navigation.side')]=effective('navigation.width')+32
    tokens={'--blog-max-width':str(effective('layout.maxWidth'))+'px','--blog-text-width':str(percent)+'%','--blog-note-width':str(note)+'%','--blog-note-offset':'-'+str(note+gap)+'%','--blog-note-ratio':str(note/100),'--blog-note-gap-ratio':str(gap/100),'--blog-rail-left':str(rails['left'])+'px','--blog-rail-right':str(rails['right'])+'px'}
    css.append(':root{'+ ';'.join(key+':'+value for key,value in tokens.items())+'}')
    side, width, mobile = effective('toc.side'), effective('toc.width'), effective('toc.mobile')
    css.append('.toc-sidebar{' + side + ':1rem;' + ('right' if side == 'left' else 'left') + ':auto;width:' + str(width) + 'px;max-width:22vw}')
    if mobile != 'hidden': css.append('@media(max-width:1199px){.toc-sidebar{display:block;position:static;width:auto;max-width:none;max-height:none;margin:1rem}.toc-sidebar ol[hidden]{display:none}}')
    css.append('.toc-mobile-toggle{display:none}@media(max-width:1199px){.toc-mobile-toggle{display:block}}')
    if effective('backTop.side') == 'left': css.append('#page-jump-btn{left:1rem;right:auto}')
    if effective('navigation.enabled'):
        side,width=effective('navigation.side'),effective('navigation.width')
        css.append('.blog-section-navigation{font-size:1rem;line-height:1.5;margin:1rem}.blog-section-navigation ul{list-style:none;padding-left:1em}.blog-section-navigation a[aria-current=page]{font-weight:bold}.blog-section-navigation a{overflow-wrap:anywhere}.blog-section-navigation summary{cursor:pointer}@media(min-width:1200px){.blog-section-navigation{position:fixed;'+side+':0;top:4rem;width:'+str(width)+'px;max-height:80vh;overflow:auto}.blog-section-navigation>summary{display:none}}')
    return public_settings, '\n'.join(css)


def checked(root, relative):
    if not isinstance(relative, str) or any(c in relative for c in '\\:\0?#'):
        raise ValueError('Invalid project path')
    if any(not p or p.startswith('.') or p.endswith(('.', ' ')) for p in relative.split('/')):
        raise ValueError('Invalid project path: ' + relative)
    result = root.joinpath(relative).resolve()
    if not result.is_relative_to(root.resolve()):
        raise ValueError('Path outside project: ' + relative)
    return result


def route(path):
    if not path.startswith('content/') or not path.endswith('.typ'):
        raise ValueError('Not a content page: ' + path)
    relative = path[len('content/'):]
    return '/' + (relative[:-9] if PurePosixPath(relative).name == 'index.typ' else relative[:-4] + '/')


def pdf_route(path):
    if not path.startswith('content/') or not path.endswith('.typ'):
        raise ValueError('Not a PDF source: ' + path)
    return '/' + path[len('content/'):-4] + '.pdf'


def overlap(a, b):
    a, b = a.casefold().rstrip('/'), b.casefold().rstrip('/')
    return a == b or a.startswith(b + '/') or b.startswith(a + '/')


def pdf_records(root, manifest, mode):
    pdfs = manifest.get('pdfs', [])
    if not isinstance(pdfs, list): raise ValueError('Invalid PDF manifest')
    ids = {p['id'] for p in manifest['pages']}
    paths = {p['path'].casefold() for p in manifest['pages']}
    targets = [route(p['path']).lstrip('/') + 'index.html' for p in manifest['pages']]
    targets += [a['path'].removeprefix('content/') for a in manifest['assets']]
    # Check physical files too: a generated download must never replace a user's file.
    physical = [p.relative_to(root / 'content').as_posix() for p in (root / 'content').rglob('*')]
    records = []
    for pdf in pdfs:
        source = checked(root, pdf['path']); target = pdf_route(pdf['path']).lstrip('/')
        if not pdf.get('id') or pdf['id'] in ids or pdf['path'].casefold() in paths:
            raise ValueError('Duplicate PDF identity or source')
        if pdf['status'] not in ('draft', 'published'): raise ValueError('Unknown PDF publication status')
        if any(overlap(target, p) for p in targets) or any(p.casefold() == target.casefold() or p.casefold().startswith(target.casefold() + '/') for p in physical):
            raise ValueError('PDF output collision: ' + target)
        ids.add(pdf['id']); paths.add(pdf['path'].casefold()); targets.append(target)
        if mode == 'preview' or pdf['status'] == 'published':
            if not source.is_file(): raise ValueError('Missing PDF source: ' + pdf['path'])
            records.append((pdf, '/' + target))
    return records


def base_path(value):
    if not isinstance(value, str) or not value.startswith('/') or not value.endswith('/'):
        raise ValueError('basePath must start and end with /')
    if value != '/' and any(not p or p in ('.', '..') for p in value[1:-1].split('/')):
        raise ValueError('Invalid basePath')
    if any(c in value for c in '\\?#:%'):
        raise ValueError('Invalid basePath')
    return quote(value, safe='/')


class HeadFacts(HTMLParser):
    def __init__(self):
        super().__init__(); self.canonical = None
    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == 'link' and values.get('rel') == 'canonical': self.canonical = values.get('href')


def website_url(value, base):
    value = value.rstrip('/')
    if value:
        url = urlsplit(value)
        if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError('websiteUrl must be an HTTPS site URL')
        if quote(unquote(url.path).rstrip('/') + '/', safe='/') != base:
            raise ValueError('websiteUrl path and basePath must agree')
        value = urlunsplit((url.scheme, url.netloc, quote(unquote(url.path), safe='/'), '', ''))
    return value


def section_navigation(records, active, base, settings):
    roots={}
    for record in sorted(records,key=lambda p:(p['order'],p['path'])):
        parts=record['route'].strip('/').split('/')
        group=roots
        for part in parts:
            node=group.setdefault(part,{'children':{},'record':None});group=node['children']
        node['record']=record
    def render(nodes):
        items=[]
        for name,node in nodes.items():
            record=node['record']
            title=escape(record['metadata'].get('title') or name or '首页') if record else escape(name)
            label=('<a href="'+escape(base.rstrip('/')+quote(record['route'],safe='/'),quote=True)+'"'+(' aria-current="page"' if record['route']==active else '')+'>'+title+'</a>') if record else '<span>'+title+'</span>'
            items.append('<li>'+label+(render(node['children']) if node['children'] else '')+'</li>')
        return '<ul>'+''.join(items)+'</ul>'
    label=escape(settings.get('label','栏目'))
    return '<details class="blog-section-navigation" open><summary>'+label+'</summary><nav aria-label="'+escape(settings.get('label','栏目'),quote=True)+'">'+render(roots)+'</nav></details><script src="'+base+'assets/composer-navigation.js"></script>'


class PageHTML(HTMLParser):
    def __init__(self, page_route, base, routes, website, public, source_url=None, feed_enabled=True, settings=None, metadata=None):
        super().__init__(convert_charrefs=False)
        self.page_route, self.base, self.routes, self.website, self.public = page_route, base, routes, website, public
        self.parts, self.links, self.metadata = [], [], {}
        self.title = False
        self.source_url = source_url or page_route
        self.canonical = False
        self.index_slots = []
        self.feed_enabled = feed_enabled
        self.settings = settings or {}
        self.skip_tag = None
        self.style_added = False
        self.site_metadata = metadata or {}

    def managed_style(self):
        if not self.style_added:
            self.parts.append('<link rel="stylesheet" href="' + self.base + 'assets/composer-theme.css">')
            self.style_added = True

    def rewrite_url(self, value):
        value = value.replace('https://cdnjs.cloudflare.com/ajax/libs/tufte-css/1.8.0/tufte.min.css', '/assets/tufte.css')
        parts = urlsplit(value)
        if parts.scheme or parts.netloc or value.startswith('#') or not value:
            return value
        # An absolute base keeps parent-relative URLs rooted after normalization.
        # urljoin('/index.html', '../assets/a.png') can otherwise lose the slash.
        path = unquote(urlsplit(urljoin('https://composer.invalid' + self.source_url, value)).path)
        path = self.routes.get(path, path)
        self.links.append(path)
        return urlunsplit(('', '', self.base.rstrip('/') + quote(path, safe='/'), parts.query, parts.fragment))

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if self.skip_tag: return
        if tag == 'link' and values.get('rel') in ('icon', 'shortcut icon') and self.site_metadata.get('icon'): return
        if tag == 'meta' and (values.get('property') == 'og:image' or values.get('name') in ('twitter:image', 'twitter:card')) and self.site_metadata.get('shareImage'): return
        disabled = {'toc.js': self.settings.get('toc', {}).get('enabled') is False, 'back-to-top.js': self.settings.get('backTop', {}).get('enabled') is False, 'math-copy.js': self.settings.get('math', {}).get('copy') is False, 'code-blocks.js': self.settings.get('code', {}).get('copy') is False and self.settings.get('code', {}).get('lineNumbers') is False}
        if tag == 'script' and disabled.get(values.get('src', '').split('/')[-1], False) or tag == 'button' and values.get('id') == 'theme-toggle' and self.settings.get('theme', {}).get('button') is False:
            self.skip_tag = tag; return
        if tag == 'link' and values.get('type') == 'application/rss+xml' and not self.feed_enabled: return
        if tag == 'link' and values.get('rel') == 'stylesheet' and values.get('href', '').split('/')[-1] not in ('tufte.css','tufted.css','theme.css','responsive.css'): self.managed_style()
        if tag == 'link' and values.get('rel') == 'canonical': self.canonical = True
        if tag == 'title': self.title = True
        if tag == 'meta' and values.get('name') in ('description', 'date', 'author'):
            self.metadata[values['name']] = values.get('content', '')
        output = []
        for name, value in attrs:
            if self.public and name.startswith('data-composer-'): continue
            if value is not None and name in ('href', 'src', 'poster'):
                value = self.rewrite_url(value)
            if tag == 'link' and values.get('rel') == 'canonical' and name == 'href':
                value = self.website.rstrip('/') + quote(self.page_route, safe='/') if self.website else value
            if tag == 'meta' and (values.get('property') in ('og:url', 'twitter:url') or values.get('name') == 'twitter:url') and name == 'content':
                value = self.website.rstrip('/') + quote(self.page_route, safe='/') if self.website else value
            output.append(name if value is None else f'{name}="{escape(value, quote=True)}"')
        self.parts.append('<' + tag + (' ' + ' '.join(output) if output else '') + '>')
        if tag == 'head': self.parts.append('<script src="' + self.base + 'assets/composer-settings.js"></script>')
        if tag == 'div' and values.get('id') == 'blog-entries': self.index_slots.append(len(self.parts))

    def handle_startendtag(self, tag, attrs):
        before = len(self.parts)
        self.handle_starttag(tag, attrs)
        if len(self.parts) > before: self.parts[-1] = self.parts[-1][:-1] + '/>'

    def handle_endtag(self, tag):
        if self.skip_tag:
            if tag == self.skip_tag: self.skip_tag = None
            return
        if tag == 'title': self.title = False
        if tag == 'head' and self.website and not self.canonical:
            self.parts.append('<link rel="canonical" href="' + escape(self.website + quote(self.page_route, safe='/'), quote=True) + '">')
        if tag == 'head':
            self.managed_style()
            for key in ('icon', 'shareImage'):
                relative = self.site_metadata.get(key)
                if not relative: continue
                asset_route = '/' + relative.removeprefix('content/')
                self.links.append(asset_route)
                url = (self.base.rstrip('/') if key == 'icon' else self.website or self.base.rstrip('/')) + quote(asset_route, safe='/')
                if key == 'icon': self.parts.append('<link rel="icon" href="' + escape(url, quote=True) + '">')
                else: self.parts.append('<meta property="og:image" content="' + escape(url, quote=True) + '"><meta name="twitter:image" content="' + escape(url, quote=True) + '"><meta name="twitter:card" content="summary_large_image">')
        self.parts.append('</' + tag + '>')

    def handle_data(self, value):
        if self.skip_tag: return
        if self.title: self.metadata['title'] = self.metadata.get('title', '') + value
        self.parts.append(value)

    def handle_decl(self, value): self.parts.append('<!' + value + '>')
    def handle_comment(self, value): self.parts.append('<!--' + value + '-->')
    def handle_entityref(self, value):
        if self.title: self.metadata['title'] = self.metadata.get('title', '') + unescape('&' + value + ';')
        self.parts.append('&' + value + ';')
    def handle_charref(self, value):
        if self.title: self.metadata['title'] = self.metadata.get('title', '') + unescape('&#' + value + ';')
        self.parts.append('&#' + value + ';')


def build(root, output, compiler, mode='public', package_cache=None):
    root, output, compiler = Path(root).resolve(), Path(output).resolve(), Path(compiler).resolve()
    if mode not in ('preview', 'public'): raise ValueError('Unknown build mode')
    if output.exists() or output == root or root.is_relative_to(output):
        raise ValueError('Build output must be a new directory, outside the source tree')
    if output.is_relative_to(root):
        raise ValueError('Build output must be outside the source tree')
    if mode == 'preview': return build_snapshot(root, output, compiler, mode, package_cache)
    # Typst can read/include arbitrary files beneath --root, even with computed
    # paths. Remove draft sources physically, rather than guessing dependencies.
    manifest = json.loads((root / 'composer-blog.json').read_text(encoding='utf-8'))
    pdf_records(root, manifest, mode)
    drafts = set()
    for page in manifest['pages'] + manifest.get('pdfs', []):
        route(page['path']); checked(root, page['path'])
        if page['status'] == 'draft': drafts.add(page['path'].casefold())
    with tempfile.TemporaryDirectory(prefix='composer-public-source-') as temporary:
        snapshot = Path(temporary)
        def copy(source, relative):
            if any(part.startswith('.') for part in PurePosixPath(relative).parts): return
            if relative.casefold() in drafts: return
            if source.is_symlink() or getattr(source, 'is_junction', lambda: False)():
                raise ValueError('Compilation dependencies cannot be links: ' + relative)
            checked(root, relative)
            destination = snapshot / relative
            if source.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                for child in source.iterdir(): copy(child, relative + '/' + child.name)
            elif source.is_file():
                if source.suffix.lower() in ('.pem', '.key', '.exe', '.dll', '.py', '.yml', '.yaml') and not relative.startswith(('content/', 'assets/')): return
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
        for relative in ('composer-blog.json', 'config.typ', 'composer/site.json', 'content', 'assets', 'tufted-lib'):
            source = root / relative
            if source.exists(): copy(source, relative)
        return build_snapshot(snapshot, output, compiler, mode, package_cache)


def build_snapshot(root, output, compiler, mode, package_cache):
    manifest = json.loads((root / 'composer-blog.json').read_text(encoding='utf-8'))
    settings, managed_css = appearance(root)
    if manifest.get('schemaVersion') != 1 or manifest.get('adapterVersion') != 1:
        raise ValueError('Unsupported project version')
    base = base_path(manifest['basePath'])
    website = website_url(manifest.get('websiteUrl', ''), base)
    site_metadata = manifest.get('metadata', {})
    for key in ('icon', 'shareImage'):
        value = site_metadata.get(key)
        if value and not any(a['path'] == value and a.get('publish') for a in manifest['assets']):
            raise ValueError('Metadata image must be a public asset: ' + value)
    version = subprocess.check_output([str(compiler), '--version'], text=True, encoding='utf-8', timeout=15)
    tinymist = 'Typst Version:' in version
    if not re.search(r'(Typst Version:\s*|typst )0\.15\.1\b', version):
        raise ValueError('Validated Typst 0.15.1 is required')
    pages, routes, ids, all_routes = [], {}, set(), set()
    for page in manifest['pages']:
        source = checked(root, page['path'])
        if (mode == 'preview' or page['status'] == 'published') and not source.is_file(): raise ValueError('Missing page: ' + page['path'])
        page_route = route(page['path'])
        if page['id'] in ids or page_route.casefold() in all_routes:
            raise ValueError('Duplicate page identity or route')
        if page['status'] not in ('draft', 'published'): raise ValueError('Unknown publication status')
        ids.add(page['id']); all_routes.add(page_route.casefold())
        routes['/' + page['path'][len('content/'):].removesuffix('.typ') + '.html'] = page_route
        if mode == 'preview' or page['status'] == 'published': pages.append((page, page_route))
    pdfs = pdf_records(root, manifest, mode)
    output.mkdir(parents=True)
    rss_settings = manifest.get('rss', {})
    rss_sections = rss_settings.get('sections', [])
    post_ids = {p['id'] for p, r in pages if p['kind'] == 'post' and (not rss_sections or any(r.startswith(section) for section in rss_sections))}
    feed_enabled = rss_settings.get('enabled', True) and bool(post_ids)
    records, diagnostics, parsed_pages = [], [], []
    def compile_page(entry):
        page, page_route = entry
        destination = output / page_route.lstrip('/') / 'index.html'
        destination.parent.mkdir(parents=True, exist_ok=True)
        args = [str(compiler), 'compile', '--root', str(root), '--font-path', str(root / 'assets'), '--format', 'html', '--input', 'page-path=' + page_route.strip('/')]
        if not tinymist: args += ['--features', 'html']
        if package_cache: args += ['--package-cache-path', str(package_cache)]
        args += [str(root / page['path']), str(destination)]
        result = subprocess.run(args, capture_output=True, text=True, encoding='utf-8', timeout=120, cwd=root)
        if result.returncode: raise RuntimeError(page['path'] + '\n' + result.stderr)
        return page, page_route, destination, result.stderr, destination.read_text(encoding='utf-8')
    # Each compiler reads the same immutable snapshot and owns a distinct output.
    # Preserve manifest order for metadata/index processing; never reuse stale output.
    with ThreadPoolExecutor(max_workers=min(4, os.cpu_count() or 1)) as pool:
        compiled_pages = list(pool.map(compile_page, pages))
    for page, page_route, destination, stderr, compiled in compiled_pages:
        diagnostics.append({'page': page['path'], 'code': 0, 'stderr': stderr})
        if not website:
            facts = HeadFacts(); facts.feed(compiled)
            if facts.canonical:
                canonical = unquote(facts.canonical)
                if not canonical.endswith(page_route): raise ValueError('Template canonical does not match page route')
                website = website_url(canonical[:-len(page_route)], base)
        parser = PageHTML(page_route, base, routes, website, mode == 'public', '/' + page['path'][len('content/'):].removesuffix('.typ') + '.html', feed_enabled, settings, site_metadata)
        parser.feed(compiled)
        records.append({'id': page['id'], 'path': page['path'], 'route': page_route, 'kind': page['kind'], 'order': page.get('order', 0), 'metadata': parser.metadata, 'links': parser.links})
        parsed_pages.append((page, destination, parser))
    # Entries are derived from compiled metadata, including unsaved page settings.
    # The explicit slot leaves all handwritten introduction/content untouched.
    for page, destination, parser in parsed_pages:
        if page['kind'] == 'section' and parser.index_slots:
            if len(parser.index_slots) != 1: raise ValueError('Duplicate blog index slot: ' + page['path'])
            posts = [r for r in records if r['kind'] == 'post' and r['route'].startswith(parser.page_route)]
            groups = {}
            for post in posts:
                date = post['metadata'].get('date', '')
                year = date[:4] if re.match(r'^\d{4}-\d{2}-\d{2}', date) else '未注明日期'
                groups.setdefault(year, []).append(post)
            html = []
            for year, entries in sorted(groups.items(), reverse=True):
                html.append('<h2>' + escape(year) + '</h2>')
                for post in sorted(entries, key=lambda p: (p['order'], p['path'])):
                    href = base.rstrip('/') + quote(post['route'], safe='/')
                    html.append('<div class="blog-entry"><div class="blog-entry-date">' + escape(post['metadata'].get('date', '')) + '</div><div class="blog-entry-content"><a href="' + escape(href, quote=True) + '">' + escape(post['metadata'].get('title', post['path'])) + '</a></div></div>')
                    parser.links.append(post['route'])
            parser.parts.insert(parser.index_slots[0], ''.join(html))
        html=''.join(parser.parts)
        if settings.get('navigation',{}).get('enabled'):
            html=html.replace('</body>',section_navigation(records,parser.page_route,base,settings['navigation'])+'</body>')
        destination.write_text(html, encoding='utf-8')
    pdf_outputs = []
    for pdf, pdf_url in pdfs:
        destination = output / pdf_url.lstrip('/')
        destination.parent.mkdir(parents=True, exist_ok=True)
        args = [str(compiler), 'compile', '--root', str(root), '--font-path', str(root / 'assets'), '--format', 'pdf']
        if package_cache: args += ['--package-cache-path', str(package_cache)]
        args += [str(root / pdf['path']), str(destination)]
        result = subprocess.run(args, capture_output=True, text=True, encoding='utf-8', timeout=120, cwd=root)
        diagnostics.append({'page': pdf['path'], 'format': 'pdf', 'code': result.returncode, 'stderr': result.stderr})
        if result.returncode: raise RuntimeError(pdf['path'] + '\n' + result.stderr)
        with destination.open('rb') as file:
            if file.read(5) != b'%PDF-': raise RuntimeError('Invalid PDF output: ' + pdf['path'])
        pdf_outputs.append({'id': pdf['id'], 'path': pdf['path'], 'route': pdf_url})
    # An asset being readable to Typst is not permission to publish that file.
    (output / 'assets').mkdir(exist_ok=True)
    (output / 'assets/composer-settings.js').write_text('window.ComposerBlogSettings=' + json.dumps(settings, ensure_ascii=True) + ';\n', encoding='utf-8')
    (output / 'assets/composer-theme.css').write_text(managed_css, encoding='utf-8')
    if settings.get('navigation',{}).get('enabled'):
        (output/'assets/composer-navigation.js').write_text("(()=>{const nav=document.querySelector('.blog-section-navigation');if(!nav)return;const wide=matchMedia('(min-width:1200px)');const update=()=>{nav.open=wide.matches||window.ComposerBlogSettings?.navigation?.mobileOpen===true};update();wide.addEventListener('change',update)})();",encoding='utf-8')
    published = {p['route'].lstrip('/').casefold() for p in pdf_outputs}
    assets = list(manifest['assets'])
    if mode == 'preview':
        # Image/diagram workbenches create files independently of the blog manifest.
        # Resolve only referenced local media for preview; publication stays explicit.
        known = {a['path'] for a in assets}
        for link in sorted({link for record in records for link in record['links']}):
            relative = link.lstrip('/')
            if Path(relative).suffix.lower() not in ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg', '.ico', '.pdf', '.mp3', '.mp4', '.webm'): continue
            candidates = ([relative] if relative.startswith('assets/') else []) + ['content/' + relative]
            for candidate in candidates:
                if candidate in known or any(part.startswith('.') for part in Path(candidate).parts): continue
                source = checked(root, candidate)
                if source.is_file():
                    assets.append({'path': candidate, 'publish': False})
                    known.add(candidate)
    for asset in assets:
        if mode == 'public' and not asset.get('publish', False): continue
        relative = asset['path']
        source = checked(root, relative)
        if source.suffix.lower() in ('.typ', '.bib', '.md', '.json', '.toml', '.yaml', '.yml', '.py', '.pem', '.key'):
            if not asset.get('publish', False): continue
            raise ValueError('Source/configuration cannot be published as an asset: ' + relative)
        if not (relative.startswith('assets/') or relative.startswith('content/')):
            raise ValueError('Asset outside content/assets')
        target = relative.removeprefix('content/')
        if any(overlap(target, p) for p in published) or (output / target).exists(): raise ValueError('Asset output collision: ' + target)
        published.add(target.casefold())
        destination = output / target
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    # Never emit a link to a draft or silently ship a missing local resource.
    for record in records:
        for link in record['links']:
            if link == '/feed.xml' and feed_enabled or link == '/sitemap.xml' and website: continue
            destination = output / link.lstrip('/')
            if not destination.is_file() and not (destination / 'index.html').is_file():
                raise ValueError(record['path'] + ': missing or unpublished target ' + link)
    if website:
        sitemap = ET.Element('urlset', xmlns='http://www.sitemaps.org/schemas/sitemap/0.9')
        for record in records:
            ET.SubElement(ET.SubElement(sitemap, 'url'), 'loc').text = website + quote(record['route'], safe='/')
        ET.ElementTree(sitemap).write(output / 'sitemap.xml', encoding='utf-8', xml_declaration=True)
        (output / 'robots.txt').write_text('User-agent: *\nAllow: /\nSitemap: ' + website + '/sitemap.xml\n', encoding='utf-8')
    rss = ET.Element('rss', version='2.0'); channel = ET.SubElement(rss, 'channel')
    ET.SubElement(channel, 'title').text = manifest['name']
    ET.SubElement(channel, 'link').text = website or base
    ET.SubElement(channel, 'description').text = manifest['name']
    for record in records:
        if record['id'] not in post_ids: continue
        item = ET.SubElement(channel, 'item')
        for key, value in [('title', record['metadata'].get('title', '')), ('link', website + quote(record['route'], safe='/')), ('description', record['metadata'].get('description', ''))]:
            ET.SubElement(item, key).text = value
        ET.SubElement(item, 'guid', isPermaLink='false').text = manifest['siteId'] + ':' + record['id']
        date = record['metadata'].get('date', '')
        try:
            if re.fullmatch(r'\d{4}-\d{2}-\d{2}', date): ET.SubElement(item, 'pubDate').text = format_datetime(datetime.fromisoformat(date).replace(tzinfo=timezone.utc))
        except ValueError: pass
    if feed_enabled: ET.ElementTree(rss).write(output / 'feed.xml', encoding='utf-8', xml_declaration=True)
    files = [{'path': p.relative_to(output).as_posix(), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest(), 'bytes': p.stat().st_size} for p in sorted(output.rglob('*')) if p.is_file()]
    return {'siteId': manifest['siteId'], 'mode': mode, 'basePath': base, 'pages': records, 'pdfs': pdf_outputs, 'files': files, 'diagnostics': diagnostics, 'compilerVersion': version}


def export_project(root, output, compiler, dependencies=(), package_cache=None):
    """Export a reviewable source subset, then compile only that subset."""
    root, output = Path(root).resolve(), Path(output).resolve()
    if output.exists() or output.is_relative_to(root) or root.is_relative_to(output):
        raise ValueError('Project export requires a new directory outside the source tree')
    original = json.loads((root / 'composer-blog.json').read_text(encoding='utf-8'))
    pages = [{key: p[key] for key in ('id', 'path', 'kind', 'status', 'order') if key in p}
             for p in original['pages'] if p['status'] == 'published']
    pdf_records(root, original, 'public')
    pdfs = [{key: p[key] for key in ('id', 'path', 'status')} for p in original.get('pdfs', []) if p['status'] == 'published']
    drafts = {p['path'].casefold() for p in original['pages'] + original.get('pdfs', []) if p['status'] != 'published'}
    paths = {'config.typ'} | {p['path'] for p in pages + pdfs}
    paths.update(p.relative_to(root).as_posix() for p in (root / 'tufted-lib').rglob('*.typ'))
    assets = [{'path': a['path'], 'publish': True} for a in original['assets'] if a.get('publish')]
    paths.update(a['path'] for a in assets)
    for relative in dependencies:
        file = checked(root, relative)
        if not relative.startswith(('content/', 'assets/')) or file.suffix.lower() not in ('.typ', '.bib', '.yaml', '.yml', '.json', '.csv', '.md', '.txt', '.svg', '.png', '.jpg', '.jpeg', '.webp', '.gif', '.pdf', '.woff', '.woff2'):
            raise ValueError('Not an eligible compilation dependency: ' + relative)
        if relative.casefold() in drafts: raise ValueError('Draft pages cannot be exported: ' + relative)
        paths.add(relative)
        if not any(a['path'] == relative for a in assets): assets.append({'path': relative, 'publish': False})
    if any(p.casefold() in drafts for p in paths): raise ValueError('A draft page is listed as an export asset')
    manifest = {key: original[key] for key in ('schemaVersion', 'adapterVersion', 'siteId', 'name', 'upstream', 'basePath', 'websiteUrl', 'templateVersion') if key in original}
    manifest.update(pages=pages, pdfs=pdfs, assets=assets)
    rss = original.get('rss', {})
    manifest['rss'] = {key: rss[key] for key in ('enabled', 'sections') if key in rss}
    metadata = original.get('metadata', {})
    manifest['metadata'] = {key: metadata[key] for key in ('icon', 'shareImage') if key in metadata}
    manifest['templateBaselines'] = {p: h for p, h in original.get('templateBaselines', {}).items() if p in paths}
    settings, _ = appearance(root)
    output.mkdir(parents=True)
    for relative in sorted(paths):
        source = checked(root, relative)
        if source.is_symlink() or not source.is_file(): raise ValueError('Missing export file: ' + relative)
        destination = checked(output, relative); destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
    (output / 'composer').mkdir(exist_ok=True)
    (output / 'composer/site.json').write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding='utf-8')
    (output / 'composer-blog.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    for name in ('build-composer.py', 'appearance-schema.json'):
        shutil.copyfile(Path(__file__).with_name(name), output / name)
    # No app, credentials, Git state, hooks or editor instrumentation are needed.
    (output / 'README-export.md').write_text('''# Independent blog project

This source export contains published pages and explicit PDF sources, local template files, public assets,
and only the additional compilation dependencies selected during export.
Draft pages and PDFs, Git history, deployment state and application credentials are excluded.
PDFs retain their original page, font and document settings; they are compiled separately from HTML.
Selected dependency source files are included in this project, but are not website assets.

Requirements: Python 3.10 or later and Typst 0.15.1 (Tinymist 0.15.8 embeds it).
Run from any directory, with explicit absolute paths:

```text
python build-composer.py --root /path/to/project --output /path/to/new-website --compiler /path/to/tinymist --mode public
```

The website output must be a new directory outside this project. No Composer app
is required. Local CSS, scripts and fonts are included. Custom package imports
require their Typst packages; use --package-cache with an independently prepared
cache for offline builds. No build hooks or automatic deployment are installed.
''', encoding='utf-8')
    with tempfile.TemporaryDirectory(prefix='composer-export-verify-') as temporary:
        verified = build(output, Path(temporary) / 'website', compiler, 'public', package_cache)
    files = [{'path': p.relative_to(output).as_posix(), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest(), 'bytes': p.stat().st_size} for p in sorted(output.rglob('*')) if p.is_file()]
    return {**verified, 'mode': 'project', 'files': files}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', required=True); parser.add_argument('--output', required=True)
    parser.add_argument('--compiler', required=True); parser.add_argument('--package-cache')
    parser.add_argument('--mode', choices=['preview', 'public', 'project'], default='public')
    parser.add_argument('--dependency', action='append', default=[])
    args = parser.parse_args()
    try:
        result = export_project(args.root, args.output, args.compiler, args.dependency, args.package_cache) if args.mode == 'project' else build(args.root, args.output, args.compiler, args.mode, args.package_cache)
        print(json.dumps(result, ensure_ascii=False))
    except Exception as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
