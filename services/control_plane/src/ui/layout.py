"""Shared layout utilities for Control Plane UI."""

from __future__ import annotations

NAV_LINKS = [
    ("/dashboard", "📊 Dashboard"),
    ("/ui/config", "⚙️ Config"),
    ("/reports/success", "✅ Success Report"),
    ("/docs", "📘 API Docs"),
]


def render_page(content_html: str, title: str = "CDC Zone Control Plane", extra_style: str = "") -> str:
    nav_html = "".join(
        f'<a href="{href}">{label}</a>'
        for href, label in NAV_LINKS
    )

    base_style = f"""
      body {{
        font-family: "Inter", "IBM Plex Sans Thai", "Sarabun", sans-serif;
        margin: 0;
        padding: 0;
        background: #f7fafc;
        color: #1f2933;
      }}
      .navbar {{
        background: #0f172a;
        color: #fff;
        padding: 0.8rem 1.5rem;
        display: flex;
        align-items: center;
        justify-content: space-between;
        box-shadow: 0 4px 12px rgba(15,23,42,0.25);
      }}
      .navbar h1 {{
        margin: 0;
        font-size: 1.3rem;
      }}
      .nav-links {{
        display: flex;
        gap: 1rem;
      }}
      .nav-links a {{
        color: #e2e8f0;
        text-decoration: none;
        padding: 0.35rem 0.75rem;
        border-radius: 8px;
        font-weight: 500;
      }}
      .nav-links a:hover {{
        background: rgba(255,255,255,0.15);
      }}
      .page-container {{
        max-width: 1200px;
        margin: 0 auto;
        padding: 24px;
      }}
    """

    return f"""
    <!DOCTYPE html>
    <html>
      <head>
        <title>{title}</title>
        <style>
          {base_style}
          {extra_style}
        </style>
      </head>
      <body>
        <div class="navbar">
          <h1>CDC Zone Control Plane</h1>
          <div class="nav-links">
            {nav_html}
          </div>
        </div>
        <div class="page-container">
          {content_html}
        </div>
      </body>
    </html>
    """


__all__ = ["render_page"]
