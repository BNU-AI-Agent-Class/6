#!/usr/bin/env python3
"""
PPT 生成脚本 —— 读取 JSON 配置文件，套用 guizang-ppt-skill 模板生成 HTML PPT。

用法:
    python generate_ppt.py ppt_config.json          # 使用默认配置
    python generate_ppt.py my_config.json           # 使用自定义配置
"""

import json
import os
import sys
import shutil
from pathlib import Path

# ============================================================
# 路径配置
# ============================================================
SKILL_ROOT = Path.home() / ".workbuddy" / "skills" / "guizang-ppt-skill"
TEMPLATE_A = SKILL_ROOT / "assets" / "template.html"
TEMPLATE_B = SKILL_ROOT / "assets" / "template-swiss.html"

# ============================================================
# Style A — 5套主题色 CSS 变量
# ============================================================
THEMES_A = {
    "墨水经典": {
        "--ink": "#0a0a0b", "--ink-rgb": "10,10,11",
        "--paper": "#f1efea", "--paper-rgb": "241,239,234",
        "--paper-tint": "#e8e5de", "--ink-tint": "#18181a",
    },
    "靛蓝瓷": {
        "--ink": "#0a1f3d", "--ink-rgb": "10,31,61",
        "--paper": "#f1f3f5", "--paper-rgb": "241,243,245",
        "--paper-tint": "#e2e5ea", "--ink-tint": "#0d2548",
    },
    "森林墨": {
        "--ink": "#1a2e1f", "--ink-rgb": "26,46,31",
        "--paper": "#f5f1e8", "--paper-rgb": "245,241,232",
        "--paper-tint": "#e8e2d6", "--ink-tint": "#1f3524",
    },
    "牛皮纸": {
        "--ink": "#2a1e13", "--ink-rgb": "42,30,19",
        "--paper": "#eedfc7", "--paper-rgb": "238,223,199",
        "--paper-tint": "#e4d3b8", "--ink-tint": "#332518",
    },
    "沙丘": {
        "--ink": "#1f1a14", "--ink-rgb": "31,26,20",
        "--paper": "#f0e6d2", "--paper-rgb": "240,230,210",
        "--paper-tint": "#e6dac2", "--ink-tint": "#2a231c",
    },
}

# ============================================================
# Style B — 4套主题色 CSS 变量
# ============================================================
THEMES_B = {
    "克莱因蓝IKB": {
        "--accent": "#002FA7", "--accent-rgb": "0,47,167",
        "--accent-on": "#ffffff", "--accent-bright": "#5B7BFF",
    },
    "柠檬黄": {
        "--accent": "#FFD500", "--accent-rgb": "255,213,0",
        "--accent-on": "#0a0a0a", "--accent-bright": "#FFE44D",
    },
    "柠檬绿": {
        "--accent": "#C5E803", "--accent-rgb": "197,232,3",
        "--accent-on": "#0a0a0a", "--accent-bright": "#D9F54D",
    },
    "安全橙": {
        "--accent": "#FF6B35", "--accent-rgb": "255,107,53",
        "--accent-on": "#ffffff", "--accent-bright": "#FF8C63",
    },
}


def load_config(config_path: str) -> dict:
    """读取并校验 JSON 配置。"""
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_template(style: str) -> str:
    """加载对应风格的 HTML 模板。"""
    path = TEMPLATE_A if style == "A" else TEMPLATE_B
    if not path.exists():
        raise FileNotFoundError(f"模板文件不存在: {path}\n请先安装 guizang-ppt-skill")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def apply_theme(template: str, style: str, theme_name: str) -> str:
    """替换模板中的主题色 CSS 变量。"""
    themes = THEMES_A if style == "A" else THEMES_B
    if theme_name not in themes:
        available = ", ".join(themes.keys())
        raise ValueError(f"未知主题 '{theme_name}'。可选: {available}")

    for var, value in themes[theme_name].items():
        # 匹配 CSS 变量定义行: --var:旧值;
        import re
        pattern = rf"({re.escape(var)}\s*:\s*)[^;]+;"
        template = re.sub(pattern, rf"\g<1>{value};", template)

    return template


def esc(text) -> str:
    """安全转义文本（避免 HTML 注入）。"""
    if not text:
        return ""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ============================================================
# Slide HTML 生成器 — 每种 type 对应一个布局模板
# ============================================================

def gen_cover(slide: dict, page_num: int, total: int) -> str:
    """Layout 1: 开场封面 (hero dark)"""
    return f'''<section class="slide hero dark">
  <div class="chrome">
    <div>{esc(slide.get("chrome_left", ""))}</div>
    <div>{esc(slide.get("chrome_right", f"{page_num:02d} / {total:02d}"))}</div>
  </div>
  <div class="frame" style="display:grid; gap:4vh; align-content:center; min-height:80vh">
    <div class="kicker" data-anim>{esc(slide.get("kicker", ""))}</div>
    <h1 class="h-hero" data-anim>{esc(slide.get("title", ""))}</h1>
    <h2 class="h-sub" data-anim>{esc(slide.get("subtitle", ""))}</h2>
    <p class="lead" style="max-width:60vw" data-anim>{esc(slide.get("lead", ""))}</p>
    <div class="meta-row" data-anim>
      <span>{esc(slide.get("author", ""))}</span>
    </div>
  </div>
  <div class="foot">
    <div>{esc(slide.get("foot_left", ""))}</div>
    <div>{esc(slide.get("foot_right", ""))}</div>
  </div>
</section>'''


def gen_divider(slide: dict, page_num: int, total: int) -> str:
    """Layout 2: 章节幕封 (hero light/dark 交替)"""
    theme = slide.get("theme", "hero light")
    return f'''<section class="slide {theme}">
  <div class="chrome">
    <div>{esc(slide.get("chrome_left", ""))}</div>
    <div>{esc(slide.get("chrome_right", f"{page_num:02d} / {total:02d}"))}</div>
  </div>
  <div class="frame" style="display:grid; gap:6vh; align-content:center; min-height:80vh">
    <div class="kicker" data-anim>{esc(slide.get("kicker", ""))}</div>
    <h1 class="h-hero" style="font-size:8.5vw" data-anim>{esc(slide.get("title", ""))}</h1>
    <p class="lead" style="max-width:55vw" data-anim>{esc(slide.get("lead", ""))}</p>
  </div>
  <div class="foot">
    <div>{esc(slide.get("foot_left", ""))}</div>
    <div>{esc(slide.get("foot_right", ""))}</div>
  </div>
</section>'''


def gen_big_numbers(slide: dict, page_num: int, total: int) -> str:
    """Layout 3: 数据大字报 — 3x2 网格"""
    stats = slide.get("stats", [])
    # 确保有偶数个 stats，最多 6 个
    stats = stats[:6]
    # 补齐到偶数
    while len(stats) % 2 != 0 and len(stats) < 6:
        stats.append({"label": "", "number": "", "note": ""})

    rows = (len(stats) + 1) // 2
    cols = min(len(stats), 2) if len(stats) <= 2 else 3
    grid_class = "grid-6" if len(stats) >= 6 else "grid-4" if len(stats) >= 4 else "grid-3"

    cards_html = ""
    for s in stats:
        cards_html += f'''      <div class="stat-card" data-anim>
        <div class="stat-label">{esc(s.get("label", ""))}</div>
        <div class="stat-nb">{esc(s.get("number", ""))}</div>
        <div class="stat-note">{esc(s.get("note", ""))}</div>
      </div>
'''

    return f'''<section class="slide light">
  <div class="chrome">
    <div>{esc(slide.get("chrome_left", ""))}</div>
    <div>{esc(slide.get("chrome_right", f"{page_num:02d} / {total:02d}"))}</div>
  </div>
  <div class="frame" style="padding-top:6vh">
    <div class="kicker" data-anim>{esc(slide.get("kicker", ""))}</div>
    <h2 class="h-xl" data-anim>{esc(slide.get("title", ""))}</h2>
    <p class="lead" style="margin-bottom:5vh" data-anim>{esc(slide.get("subtitle", ""))}</p>
    <div class="{grid_class}" style="margin-top:6vh">
{cards_html}    </div>
  </div>
  <div class="foot">
    <div>{esc(slide.get("foot_left", ""))}</div>
    <div>{esc(slide.get("foot_right", ""))}</div>
  </div>
</section>'''


def gen_quote_image(slide: dict, page_num: int, total: int) -> str:
    """Layout 4: 左文右图 (金句 + 配图)"""
    img_html = ""
    if slide.get("image"):
        img_html = f'''    <figure class="frame-img r-16x10" data-anim>
      <img src="{esc(slide['image'])}" alt="{esc(slide.get('image_caption', ''))}">
      <figcaption class="img-cap">{esc(slide.get('image_caption', ''))}</figcaption>
    </figure>'''

    callout_html = ""
    if slide.get("callout_text"):
        callout_html = f'''      <div class="callout" data-anim>
        "{esc(slide['callout_text']).replace(chr(10), '<br>')}"
        <div class="callout-src">{esc(slide.get('callout_source', ''))}</div>
      </div>'''

    return f'''<section class="slide light">
  <div class="chrome">
    <div>{esc(slide.get("chrome_left", ""))}</div>
    <div>{esc(slide.get("chrome_right", f"{page_num:02d} / {total:02d}"))}</div>
  </div>
  <div class="frame grid-2-7-5" style="padding-top:6vh">
    <div style="display:flex; flex-direction:column; justify-content:space-between; gap:3vh">
      <div>
        <div class="kicker" data-anim>{esc(slide.get("kicker", ""))}</div>
        <h2 class="h-xl" style="white-space:nowrap; font-size:7.2vw" data-anim>{esc(slide.get("title", ""))}</h2>
        <p class="lead" style="margin-top:3vh" data-anim>{esc(slide.get("lead", ""))}</p>
      </div>
{callout_html}    </div>
{img_html}  </div>
  <div class="foot">
    <div>{esc(slide.get("foot_left", ""))}</div>
    <div>{esc(slide.get("foot_right", ""))}</div>
  </div>
</section>'''


def gen_image_grid(slide: dict, page_num: int, total: int) -> str:
    """Layout 5: 图片网格 — 2x3 六图"""
    images = slide.get("images", [])[:6]
    # 确定网格类名
    n = len(images)
    if n >= 6:
        grid_class = "grid-3-3"
    elif n >= 4:
        grid_class = "grid-4"
    else:
        grid_class = "grid-3"

    imgs_html = ""
    for img in images:
        imgs_html += f'''      <figure class="frame-img" style="height:26vh" data-anim>
        <img src="{esc(img.get('src', ''))}" alt="{esc(img.get('caption', ''))}">
        <figcaption class="img-cap">{esc(img.get('caption', ''))}</figcaption>
      </figure>
'''

    return f'''<section class="slide light">
  <div class="chrome">
    <div>{esc(slide.get("chrome_left", ""))}</div>
    <div>{esc(slide.get("chrome_right", f"{page_num:02d} / {total:02d}"))}</div>
  </div>
  <div class="frame" style="padding-top:5vh">
    <div class="kicker" data-anim>{esc(slide.get("kicker", ""))}</div>
    <h2 class="h-xl" data-anim>{esc(slide.get("title", ""))}</h2>
    <div class="{grid_class}" style="margin-top:4vh">
{imgs_html}    </div>
  </div>
  <div class="foot">
    <div>{esc(slide.get("foot_left", ""))}</div>
    <div>{esc(slide.get("foot_right", ""))}</div>
  </div>
</section>'''


def gen_pipeline(slide: dict, page_num: int, total: int) -> str:
    """Layout 6: 流水线 — 多阶段步骤"""
    pipelines = slide.get("pipelines", [])
    pipes_html = ""
    step_counter = 0
    for pipe in pipelines:
        steps = pipe.get("steps", [])
        steps_html = ""
        for step in steps:
            step_counter += 1
            steps_html += f'''        <div class="step" data-anim="step">
          <div class="step-nb">{step_counter:02d}</div>
          <div class="step-title">{esc(step.get("title", ""))}</div>
          <div class="step-desc">{esc(step.get("desc", ""))}</div>
        </div>
'''
        pipes_html += f'''    <div class="pipeline-section">
      <div class="pipeline-label">{esc(pipe.get("label", ""))}</div>
      <div class="pipeline">
{steps_html}      </div>
    </div>
'''

    return f'''<section class="slide light" data-animate="pipeline">
  <div class="chrome">
    <div>{esc(slide.get("chrome_left", ""))}</div>
    <div>{esc(slide.get("chrome_right", f"{page_num:02d} / {total:02d}"))}</div>
  </div>
  <div class="frame">
    <div class="kicker">{esc(slide.get("kicker", ""))}</div>
    <h2 class="h-xl">{esc(slide.get("title", ""))}</h2>
{pipes_html}  </div>
  <div class="foot">
    <div>{esc(slide.get("foot_left", ""))}</div>
    <div>{esc(slide.get("foot_right", ""))}</div>
  </div>
</section>'''


def gen_question(slide: dict, page_num: int, total: int) -> str:
    """Layout 7: 悬念问题页 (hero dark)"""
    lines = slide.get("title_lines", [])
    lines_html = ""
    for line in lines:
        lines_html += f'      <span data-anim style="display:block">{esc(line)}</span>\n'

    return f'''<section class="slide hero dark">
  <div class="chrome">
    <div>{esc(slide.get("chrome_left", ""))}</div>
    <div>{esc(slide.get("chrome_right", f"{page_num:02d} / {total:02d}"))}</div>
  </div>
  <div class="frame" style="display:grid; gap:8vh; align-content:center; min-height:80vh">
    <div class="kicker" data-anim>{esc(slide.get("kicker", ""))}</div>
    <h1 class="h-hero" style="font-size:7vw; line-height:1.15">
{lines_html}    </h1>
    <p class="lead" style="max-width:50vw" data-anim>{esc(slide.get("lead", ""))}</p>
  </div>
  <div class="foot">
    <div>{esc(slide.get("foot_left", ""))}</div>
    <div>{esc(slide.get("foot_right", ""))}</div>
  </div>
</section>'''


def gen_big_quote(slide: dict, page_num: int, total: int) -> str:
    """Layout 8: 大引用页 (衬线金句)"""
    quote_lines = slide.get("quote_cn", "").replace("\n", "<br>")
    return f'''<section class="slide light" data-animate="quote">
  <div class="chrome">
    <div>{esc(slide.get("chrome_left", ""))}</div>
    <div>{esc(slide.get("chrome_right", f"{page_num:02d} / {total:02d}"))}</div>
  </div>
  <div class="frame" style="display:grid; gap:5vh; align-content:center; min-height:80vh">
    <div class="kicker" data-anim>{esc(slide.get("kicker", ""))}</div>
    <blockquote style="font-family:var(--serif-zh); font-weight:700; font-size:5.8vw; line-height:1.2; letter-spacing:-.01em; max-width:72vw">
      <span data-anim="line" style="display:block">"{quote_lines}"</span>
    </blockquote>
    <p class="lead" style="max-width:55vw; opacity:.65" data-anim>{esc(slide.get("quote_en", ""))}</p>
    <div class="meta-row" data-anim>
      <span>{esc(slide.get("source", ""))}</span>
    </div>
  </div>
  <div class="foot">
    <div>{esc(slide.get("foot_left", ""))}</div>
    <div>{esc(slide.get("foot_right", ""))}</div>
  </div>
</section>'''


def gen_compare(slide: dict, page_num: int, total: int) -> str:
    """Layout 9: 并列对比 (Before / After)"""
    before = slide.get("before", {})
    after = slide.get("after", {})

    def gen_items(items):
        html = ""
        for item in items:
            html += f'          <li>{esc(item)}</li>\n'
        return html

    return f'''<section class="slide light" data-animate="directional">
  <div class="chrome">
    <div>{esc(slide.get("chrome_left", ""))}</div>
    <div>{esc(slide.get("chrome_right", f"{page_num:02d} / {total:02d}"))}</div>
  </div>
  <div class="frame" style="padding-top:5vh">
    <div class="kicker" data-anim>{esc(slide.get("kicker", ""))}</div>
    <h2 class="h-xl" style="margin-bottom:4vh" data-anim>{esc(slide.get("title", ""))}</h2>
    <div class="grid-2-6-6" style="gap:5vw 4vh">
      <div data-anim="left" style="padding:3vh 2vw; border-left:3px solid currentColor; opacity:.55">
        <div class="kicker" style="opacity:.9">{esc(before.get("label", ""))}</div>
        <h3 class="h-md" style="margin-top:2vh">{esc(before.get("title", ""))}</h3>
        <ul style="margin-top:3vh; padding-left:1.2em; display:flex; flex-direction:column; gap:1.4vh; font-family:var(--sans-zh); font-size:max(14px,1.1vw); line-height:1.55">
{gen_items(before.get("items", []))}        </ul>
      </div>
      <div data-anim="right" style="padding:3vh 2vw; border-left:3px solid currentColor">
        <div class="kicker" style="opacity:.9">{esc(after.get("label", ""))}</div>
        <h3 class="h-md" style="margin-top:2vh">{esc(after.get("title", ""))}</h3>
        <ul style="margin-top:3vh; padding-left:1.2em; display:flex; flex-direction:column; gap:1.4vh; font-family:var(--sans-zh); font-size:max(14px,1.1vw); line-height:1.55">
{gen_items(after.get("items", []))}        </ul>
      </div>
    </div>
  </div>
  <div class="foot">
    <div>{esc(slide.get("foot_left", ""))}</div>
    <div>{esc(slide.get("foot_right", ""))}</div>
  </div>
</section>'''


def gen_mixed(slide: dict, page_num: int, total: int) -> str:
    """Layout 10: 图文混排 (大段文字 + 小配图)"""
    img_html = ""
    if slide.get("image"):
        img_html = f'''    <figure class="frame-img r-3x4" data-anim>
      <img src="{esc(slide['image'])}" alt="{esc(slide.get('image_caption', ''))}">
      <figcaption class="img-cap">{esc(slide.get('image_caption', ''))}</figcaption>
    </figure>'''

    callout_html = ""
    if slide.get("callout_text"):
        callout_html = f'''      <div class="callout" style="margin-top:3vh" data-anim>
        "{esc(slide['callout_text']).replace(chr(10), '<br>')}"
        <div class="callout-src">{esc(slide.get('callout_source', ''))}</div>
      </div>'''

    return f'''<section class="slide light">
  <div class="chrome">
    <div>{esc(slide.get("chrome_left", ""))}</div>
    <div>{esc(slide.get("chrome_right", f"{page_num:02d} / {total:02d}"))}</div>
  </div>
  <div class="frame grid-2-8-4" style="padding-top:6vh">
    <div>
      <div class="kicker" data-anim>{esc(slide.get("kicker", ""))}</div>
      <h2 class="h-xl" style="margin-top:1vh; margin-bottom:3vh" data-anim>{esc(slide.get("title", ""))}</h2>
      <p class="lead" style="margin-bottom:3vh" data-anim>{esc(slide.get("lead", ""))}</p>
      <p data-anim style="font-family:var(--sans-zh); font-size:max(14px,1.15vw); line-height:1.75; opacity:.78; margin-bottom:2.4vh">{esc(slide.get("body", ""))}</p>
{callout_html}    </div>
{img_html}  </div>
  <div class="foot">
    <div>{esc(slide.get("foot_left", ""))}</div>
    <div>{esc(slide.get("foot_right", ""))}</div>
  </div>
</section>'''


# ============================================================
# 布局生成器映射
# ============================================================
GENERATORS = {
    "cover":        gen_cover,
    "divider":      gen_divider,
    "big_numbers":  gen_big_numbers,
    "quote_image":  gen_quote_image,
    "image_grid":   gen_image_grid,
    "pipeline":     gen_pipeline,
    "question":     gen_question,
    "big_quote":    gen_big_quote,
    "compare":      gen_compare,
    "mixed":        gen_mixed,
}


def generate_slides(slides: list) -> str:
    """遍历 slides 配置，生成所有页面的 HTML。"""
    total = len(slides)
    html_parts = []

    for i, slide in enumerate(slides):
        page_num = i + 1
        slide_type = slide.get("type", "")

        if slide_type not in GENERATORS:
            print(f"  ⚠ 跳过第 {page_num} 页: 未知类型 '{slide_type}'")
            continue

        html = GENERATORS[slide_type](slide, page_num, total)
        html_parts.append(html)

    return "\n\n".join(html_parts)


def generate(config_path: str):
    """主流程: 读取配置 → 生成 HTML → 输出。"""
    print(f"📄 读取配置: {config_path}")
    config = load_config(config_path)

    meta = config.get("meta", {})
    style = meta.get("style", "A")
    theme = meta.get("theme", "墨水经典" if style == "A" else "克莱因蓝IKB")
    title = meta.get("title", "PPT")
    output_dir = meta.get("output_dir", "ppt_output")

    slides = config.get("slides", [])
    if not slides:
        print("❌ 配置中没有 slides，请至少添加一页。")
        return

    print(f"🎨 风格: {'电子杂志风' if style == 'A' else '瑞士国际主义风'}")
    print(f"🎨 主题: {theme}")
    print(f"📊 页数: {len(slides)}")

    # 加载模板
    print("📂 加载模板...")
    template = load_template(style)

    # 应用主题
    print("🎨 应用主题色...")
    template = apply_theme(template, style, theme)

    # 替换标题
    template = template.replace("[必填] 替换为 PPT 标题", title)
    template = template.replace("[必填] Deck 标题", title)

    # 生成 slides
    print("📝 生成页面...")
    slides_html = generate_slides(slides)

    # 插入 slides（替换 <!-- SLIDES_HERE 开头的注释块）
    import re
    template = re.sub(
        r"<!-- SLIDES_HERE.*?(?=<section class=\"slide|</div>\s*<div id=\"nav\")",
        slides_html + "\n\n",
        template,
        flags=re.DOTALL,
    )

    # 如果正则没匹配到，用更简单的方式
    if "<!-- SLIDES_HERE" in template:
        template = template.replace("<!-- SLIDES_HERE", slides_html + "\n<!--")

    # 清理 Swiss 模板中的 [必填] 示例页（如果存在）
    if style == "B":
        # Swiss 模板自带示例页，我们需要移除并替换
        # 简单处理: 将 SLIDES_HERE 注释到 <div id="nav"> 之间的 <section> 替换掉
        deck_start = template.find('<div id="deck">')
        nav_start = template.find('<div id="nav">')
        if deck_start > 0 and nav_start > deck_start:
            before = template[:deck_start + len('<div id="deck">')]
            after = template[nav_start:]
            template = before + "\n" + slides_html + "\n\n" + after

    # 输出
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    img_dir = out_path / "images"
    img_dir.mkdir(exist_ok=True)

    output_file = out_path / "index.html"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(template)

    print(f"\n✅ 生成完成: {output_file}")
    print(f"📁 图片目录: {img_dir}")
    print(f"🌐 直接用浏览器打开 {output_file} 即可预览")


# ============================================================
# CLI 入口
# ============================================================
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        # 尝试默认配置
        default_config = Path.cwd() / "ppt_config.json"
        if default_config.exists():
            config_path = str(default_config)
        else:
            print("请指定配置文件路径，或创建 ppt_config.json")
            sys.exit(1)
    else:
        config_path = sys.argv[1]

    try:
        generate(config_path)
    except Exception as e:
        print(f"❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
