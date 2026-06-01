"""HTML landing page for the rucio-mcp HTTP server root."""

from __future__ import annotations

import base64
from importlib.resources import files as _pkg_files


# Rucio assets embedded as base64 data URIs — no static-file route needed.
# Source + license: src/rucio_mcp/data/media/images/README.md
def _b64_data_uri(filename: str, mime: str) -> str:
    data = (_pkg_files("rucio_mcp.data") / "media" / "images" / filename).read_bytes()
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


_FAVICON_DATA_URI = _b64_data_uri("favicon.ico", "image/png")
_LOGO_DATA_URI = _b64_data_uri("logo.png", "image/png")

_GITHUB_ICON = (
    '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">'
    '<path d="M12 2C6.477 2 2 6.477 2 12c0 4.42 2.865 8.166 6.839 9.489.5.092.682-.217'
    ".682-.482 0-.237-.008-.866-.013-1.7-2.782.603-3.369-1.342-3.369-1.342-.454-1.155"
    "-1.11-1.462-1.11-1.462-.908-.62.069-.608.069-.608 1.003.07 1.531 1.03 1.531 1.03"
    ".892 1.529 2.341 1.087 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.11"
    "-4.555-4.943 0-1.091.39-1.984 1.029-2.683-.103-.253-.446-1.27.098-2.647 0 0 "
    ".84-.269 2.75 1.025A9.578 9.578 0 0 1 12 6.836c.85.004 1.705.114 2.504.336 "
    "1.909-1.294 2.747-1.025 2.747-1.025.546 1.377.202 2.394.1 2.647.64.699 1.028 "
    "1.592 1.028 2.683 0 3.842-2.339 4.687-4.566 4.935.359.309.678.919.678 1.852 "
    "0 1.336-.012 2.415-.012 2.743 0 .267.18.579.688.481C19.138 20.163 22 16.418 "
    '22 12c0-5.523-4.477-10-10-10z"/></svg>'
)

_BOOK_ICON = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" '
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<path d="M12 6.042A8.967 8.967 0 0 0 6 3.75c-1.052 0-2.062.18-3 .512v14.25A8.987 '
    "8.987 0 0 1 6 18c2.305 0 4.408.867 6 2.292m0-14.25a8.966 8.966 0 0 1 6-2.292c1.052 "
    "0 2.062.18 3 .512v14.25A8.987 8.987 0 0 0 18 18a8.967 8.967 0 0 0-6 2.292m0-14.25v14.25"
    '"/></svg>'
)

_COPY_ICON = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" '
    'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<rect x="9" y="9" width="13" height="13" rx="2"/>'
    '<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>'
    "</svg>"
)


_CLIENTS = [
    ("claude", "Claude Code", "claude mcp add --transport http {name} {url}"),
    ("codex", "Codex", "codex mcp add {name} --url {url}"),
    ("gemini", "Gemini", "gemini mcp add --transport http {name} {url}"),
    ("opencode", "OpenCode", "opencode mcp add {name} {url}"),
]


def _quick_start_section(sites: list[str], base_url: str) -> str:
    """Render a tabbed quick-start block with one install command per client."""
    first_url = base_url.rstrip("/") + f"/site/{sites[0]}"
    first_name = f"rucio-{sites[0]}"

    # Site selector (only shown when multiple sites are configured)
    if len(sites) > 1:
        options = "\n".join(
            f'          <option value="{base_url.rstrip("/")}/site/{s}" '
            f'data-name="rucio-{s}">{s}</option>'
            for s in sites
        )
        site_select = f"""
        <div class="qs-site-select">
          <label class="qs-site-label" for="qs-site">Site</label>
          <select id="qs-site" class="qs-select" onchange="qsSiteChange(this)">
{options}
          </select>
        </div>"""
    else:
        site_select = ""

    # One hidden <code> block per client; JS swaps visibility on tab click
    cmd_blocks = "\n".join(
        f'      <div class="qs-cmd{" qs-active" if i == 0 else ""}" '
        f'id="qs-cmd-{cid}" data-tpl="{tpl}">'
        f'<code class="qs-code" id="qs-code-{cid}">'
        f"{tpl.format(name=first_name, url=first_url)}"
        f"</code>"
        f'<button class="copy-btn qs-copy" onclick="qsCopy(\'{cid}\')" title="Copy">'
        f"{_COPY_ICON}</button></div>"
        for i, (cid, _label, tpl) in enumerate(_CLIENTS)
    )

    tabs = "\n".join(
        f'      <button class="qs-tab{" qs-tab-active" if i == 0 else ""}" '
        f'data-client="{cid}" onclick="qsTab(\'{cid}\')">{label}</button>'
        for i, (cid, label, _) in enumerate(_CLIENTS)
    )

    return f"""
    <div class="qs-block fade-in d3">{site_select}
      <p class="section-label" style="margin-bottom:12px;">Quick start</p>
      <div class="qs-tabs">
{tabs}
      </div>
      <div class="qs-body">
{cmd_blocks}
      </div>
    </div>"""


def _site_row(site: str, base_url: str) -> str:
    mcp_url = base_url.rstrip("/") + f"/site/{site}"
    return f"""
      <div class="site-card">
        <div class="site-info">
          <div class="site-name">{site}</div>
          <div class="site-url" id="url-{site}">{mcp_url}</div>
        </div>
        <div class="site-right">
          <span class="site-badge">oidc</span>
          <button class="copy-btn" onclick="copyUrl('{site}')" title="Copy MCP URL">
            {_COPY_ICON}
          </button>
        </div>
      </div>"""


def make_landing_html(
    sites: list[str], resource_url: str, version: str, read_only: bool = False
) -> str:
    """Return the HTML landing page for the given server configuration."""
    site_rows = "\n".join(_site_row(s, resource_url) for s in sites)
    if read_only:
        mode_badge = '<span class="mode-badge mode-readonly">read-only</span>'
    else:
        mode_badge = '<span class="mode-badge mode-readwrite">read/write</span>'
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>rucio-mcp</title>
  <link rel="icon" type="image/png" href="{_FAVICON_DATA_URI}">
  <style>
    :root {{
      --canvas:    #FBFBFA;
      --surface:   #FFFFFF;
      --border:    #EAEAEA;
      --text:      #111111;
      --muted:     #787774;
      --badge-bg:  #EDF3EC;
      --badge-fg:  #346538;
      --ro-bg:     #FBF3DB;
      --ro-fg:     #956400;
      --sans: 'SF Pro Display', 'Helvetica Neue', system-ui, sans-serif;
      --mono: 'SF Mono', 'Geist Mono', 'JetBrains Mono', ui-monospace, monospace;
    }}
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: var(--sans);
      background: var(--canvas);
      color: var(--text);
      line-height: 1.6;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
    }}
    a {{ color: inherit; text-decoration: none; }}

    /* ── header ── */
    header {{
      border-bottom: 1px solid var(--border);
      padding: 20px 48px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      background: var(--surface);
    }}
    .logo {{ font-size: 14px; font-weight: 600; letter-spacing: -0.01em; }}
    .version {{
      font-family: var(--mono);
      font-size: 11px;
      color: var(--muted);
      background: var(--canvas);
      border: 1px solid var(--border);
      padding: 2px 8px;
      border-radius: 4px;
    }}

    /* ── main ── */
    main {{
      flex: 1;
      max-width: 860px;
      margin: 0 auto;
      padding: 72px 48px 56px;
      width: 100%;
    }}
    /* ── rucio logo ── */
    .rucio-logo-link {{
      display: block;
      width: fit-content;
      margin: 0 auto 40px;
      opacity: 0.88;
      transition: opacity 200ms ease;
    }}
    .rucio-logo-link:hover {{ opacity: 1; }}
    .rucio-logo {{ height: 52px; width: auto; display: block; }}

    .hero-label {{
      font-size: 11px;
      font-weight: 500;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--muted);
      margin-bottom: 16px;
    }}
    h1 {{
      font-size: 40px;
      font-weight: 500;
      letter-spacing: -0.03em;
      line-height: 1.1;
      margin-bottom: 14px;
    }}
    .subtitle {{
      font-size: 15px;
      color: var(--muted);
      max-width: 480px;
      margin-bottom: 56px;
    }}

    /* ── sites ── */
    .section-label {{
      font-size: 11px;
      font-weight: 500;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--muted);
      margin-bottom: 12px;
    }}
    .sites-list {{
      border: 1px solid var(--border);
      border-radius: 8px;
      overflow: hidden;
      margin-bottom: 48px;
    }}
    .site-card {{
      background: var(--surface);
      padding: 20px 24px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      border-bottom: 1px solid var(--border);
      transition: background 150ms ease;
    }}
    .site-card:last-child {{ border-bottom: none; }}
    .site-card:hover {{ background: var(--canvas); }}
    .site-name {{ font-size: 14px; font-weight: 500; margin-bottom: 3px; }}
    .site-url {{
      font-family: var(--mono);
      font-size: 12px;
      color: var(--muted);
    }}
    .site-right {{ display: flex; align-items: center; gap: 12px; }}
    .site-badge {{
      font-size: 10px;
      font-weight: 600;
      letter-spacing: 0.07em;
      text-transform: uppercase;
      background: var(--badge-bg);
      color: var(--badge-fg);
      padding: 3px 10px;
      border-radius: 9999px;
    }}
    .copy-btn {{
      background: none;
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 5px;
      cursor: pointer;
      color: var(--muted);
      display: flex;
      align-items: center;
      transition: color 150ms ease, border-color 150ms ease;
      position: relative;
    }}
    .copy-btn:hover {{ color: var(--text); border-color: #ccc; }}
    .copy-btn svg {{ width: 14px; height: 14px; }}
    .copy-btn.copied {{ color: var(--badge-fg); border-color: var(--badge-bg); }}

    /* ── mode badge ── */
    .mode-badge {{
      font-size: 10px;
      font-weight: 600;
      letter-spacing: 0.07em;
      text-transform: uppercase;
      padding: 3px 10px;
      border-radius: 9999px;
    }}
    .mode-readwrite {{ background: var(--badge-bg); color: var(--badge-fg); }}
    .mode-readonly  {{ background: var(--ro-bg);    color: var(--ro-fg); }}

    /* ── links ── */
    .links-row {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 12px;
      margin-bottom: 0;
    }}
    .link-card {{
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 20px 24px;
      display: flex;
      align-items: center;
      gap: 16px;
      transition: box-shadow 200ms ease, background 150ms ease;
      cursor: pointer;
    }}
    .link-card:hover {{
      box-shadow: 0 2px 8px rgba(0,0,0,0.04);
      background: var(--surface);
    }}
    .link-icon {{
      width: 20px;
      height: 20px;
      color: var(--muted);
      flex-shrink: 0;
    }}
    .link-title {{ font-size: 14px; font-weight: 500; margin-bottom: 2px; }}
    .link-desc {{ font-size: 12px; color: var(--muted); }}

    /* ── footer ── */
    footer {{
      border-top: 1px solid var(--border);
      padding: 16px 48px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      background: var(--surface);
    }}
    .footer-text {{ font-size: 12px; color: var(--muted); }}

    /* ── quick start ── */
    .qs-block {{ margin-bottom: 48px; }}
    .qs-site-select {{
      display: flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 16px;
    }}
    .qs-site-label {{
      font-size: 11px;
      font-weight: 500;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: var(--muted);
    }}
    .qs-select {{
      font-family: var(--mono);
      font-size: 12px;
      color: var(--text);
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 4px 8px;
      cursor: pointer;
    }}
    .qs-tabs {{
      display: flex;
      gap: 2px;
      border-bottom: 1px solid var(--border);
      margin-bottom: 0;
    }}
    .qs-tab {{
      font-family: var(--sans);
      font-size: 12px;
      font-weight: 500;
      color: var(--muted);
      background: none;
      border: none;
      border-bottom: 2px solid transparent;
      padding: 8px 14px;
      cursor: pointer;
      margin-bottom: -1px;
      transition: color 150ms ease, border-color 150ms ease;
    }}
    .qs-tab:hover {{ color: var(--text); }}
    .qs-tab-active {{ color: var(--text); border-bottom-color: var(--text); }}
    .qs-body {{
      border: 1px solid var(--border);
      border-top: none;
      border-radius: 0 0 8px 8px;
      overflow: hidden;
    }}
    .qs-cmd {{
      display: none;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 14px 16px;
      background: var(--surface);
    }}
    .qs-active {{ display: flex; }}
    .qs-code {{
      font-family: var(--mono);
      font-size: 12px;
      color: var(--text);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      flex: 1;
    }}

    /* ── animations ── */
    .fade-in {{
      opacity: 0;
      transform: translateY(10px);
      animation: fadeUp 500ms cubic-bezier(0.16, 1, 0.3, 1) forwards;
    }}
    .site-card {{ --index: 0; }}
    @keyframes fadeUp {{ to {{ opacity: 1; transform: translateY(0); }} }}
    .d1 {{ animation-delay: 60ms; }}
    .d2 {{ animation-delay: 120ms; }}
    .d3 {{ animation-delay: 180ms; }}
    .d4 {{ animation-delay: 240ms; }}
  </style>
</head>
<body>
  <header>
    <span class="logo">rucio-mcp</span>
    <div style="display:flex;align-items:center;gap:8px;">
      {mode_badge}
      <span class="version">{version}</span>
    </div>
  </header>

  <main>
    <a href="https://rucio.cern.ch/" class="rucio-logo-link fade-in" target="_blank" rel="noopener noreferrer">
      <img src="{_LOGO_DATA_URI}" alt="Rucio" class="rucio-logo">
    </a>
    <p class="hero-label fade-in d1">MCP server</p>
    <h1 class="fade-in d1">Rucio data management<br>for AI assistants.</h1>
    <p class="subtitle fade-in d2">
      Exposes Rucio data management operations as tools for language models.
      Connect your MCP client to a site below.
    </p>

    {_quick_start_section(sites, resource_url)}

    <p class="section-label fade-in d3">Configured OIDC sites</p>
    <div class="sites-list fade-in d3">
{site_rows}
    </div>

    <div class="links-row fade-in d4">
      <a href="https://rucio-mcp.readthedocs.io/" class="link-card" target="_blank" rel="noopener noreferrer">
        <span class="link-icon">{_BOOK_ICON}</span>
        <div>
          <div class="link-title">Documentation</div>
          <div class="link-desc">Setup guides, OAuth flow, API reference</div>
        </div>
      </a>
      <a href="https://github.com/kratsg/rucio-mcp" class="link-card" target="_blank" rel="noopener noreferrer">
        <span class="link-icon">{_GITHUB_ICON}</span>
        <div>
          <div class="link-title">GitHub</div>
          <div class="link-desc">Source code, issues, releases</div>
        </div>
      </a>
    </div>
  </main>

  <footer>
    <span class="footer-text">rucio-mcp &mdash; MCP server for Rucio</span>
    <span class="footer-text">&copy; <a href="https://giordonstark.com/" target="_blank" rel="noopener noreferrer" style="color:inherit;text-decoration:underline;text-underline-offset:3px;">Giordon Stark</a></span>
  </footer>

  <script>
    function copyUrl(site) {{
      const el = document.getElementById('url-' + site);
      if (!el) return;
      navigator.clipboard.writeText(el.textContent.trim()).then(() => {{
        const btn = el.closest('.site-card').querySelector('.copy-btn');
        if (btn) {{
          btn.classList.add('copied');
          setTimeout(() => btn.classList.remove('copied'), 1500);
        }}
      }});
    }}

    function qsTab(clientId) {{
      document.querySelectorAll('.qs-tab').forEach(t =>
        t.classList.toggle('qs-tab-active', t.dataset.client === clientId));
      document.querySelectorAll('.qs-cmd').forEach(c =>
        c.classList.toggle('qs-active', c.id === 'qs-cmd-' + clientId));
    }}

    function qsCopy(clientId) {{
      const el = document.getElementById('qs-code-' + clientId);
      if (!el) return;
      navigator.clipboard.writeText(el.textContent.trim()).then(() => {{
        const btn = document.querySelector('#qs-cmd-' + clientId + ' .qs-copy');
        if (btn) {{
          btn.classList.add('copied');
          setTimeout(() => btn.classList.remove('copied'), 1500);
        }}
      }});
    }}

    function qsSiteChange(sel) {{
      const url = sel.value;
      const name = sel.options[sel.selectedIndex].dataset.name;
      document.querySelectorAll('.qs-cmd').forEach(cmd => {{
        const tpl = cmd.dataset.tpl;
        const cid = cmd.id.replace('qs-cmd-', '');
        const code = document.getElementById('qs-code-' + cid);
        if (code && tpl) code.textContent = tpl.replace('{{name}}', name).replace('{{url}}', url);
      }});
    }}
  </script>
</body>
</html>
"""
