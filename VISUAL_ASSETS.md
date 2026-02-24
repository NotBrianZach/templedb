# TempleDB Visual Assets Gallery

This document showcases all the vector art created for TempleDB.

---

## 🎨 Banner

**File:** `assets/banner.svg` (800x200)

![TempleDB Banner](assets/banner.svg)

**Usage:**
- README header
- Documentation sites
- Presentations
- Social media

---

## 🏛️ Logo

**File:** `assets/logo.svg` (200x200)

<div align="center">

![TempleDB Logo](assets/logo.svg)

</div>

**Design Elements:**
- Temple pediment (top triangle) representing structure
- Four columns symbolizing database tables/architecture
- Database cylinders at the base
- Data flow lines connecting temple to database
- Color scheme: Cyan (#00d4ff) for data, Red (#e94560) for structure

**Usage:**
- Documentation
- Presentations
- Project icons
- Badges

---

## 🔷 Small Icon

**File:** `assets/icon-small.svg` (64x64)

<div align="center">

![TempleDB Icon](assets/icon-small.svg)

</div>

**Usage:**
- CLI tools
- Favicons
- App icons
- Small displays
- Badges

---

## 🎮 TempleOS Tribute

**File:** `assets/templeos-tribute.svg` (640x480)

<div align="center">

![TempleOS Tribute](assets/templeos-tribute.svg)

</div>

**Design Elements:**
- Authentic TempleOS 16-color VGA palette
- ASCII-art style temple
- Classic window frame and border
- Feature list in TempleOS style
- Prominent tribute to Terry A. Davis

**VGA Color Palette:**
```
Black    #000000    Dark Gray   #555555
Blue     #0000AA    Light Blue  #5555FF
Green    #00AA00    Light Green #55FF55
Cyan     #00AAAA    Light Cyan  #55FFFF
Red      #AA0000    Light Red   #FF5555
Magenta  #AA00AA    Light Mag.  #FF55FF
Brown    #AA5500    Yellow      #FFFF55
Lt Gray  #AAAAAA    White       #FFFFFF
```

**Usage:**
- Tribute section in README
- TempleOS-inspired presentations
- Historical/philosophical documentation
- Community showcases

---

## 🎨 Design System

### Color Palette

**Primary Colors:**
- **Cyan:** `#00d4ff` - Technology, data, flow
- **Red/Pink:** `#e94560` - Structure, temple, foundation
- **Light Magenta:** `#ff6b9d` - Accents, highlights

**Backgrounds:**
- **Deep Navy:** `#0a0e27` - Main background
- **Dark Blue:** `#1a1a2e` - Secondary background
- **Mid Blue:** `#0f3460` - Tertiary elements
- **Border Blue:** `#16213e` - Borders, dividers

**Accents:**
- **Grid Gray:** `#1a1a3e` - Background patterns
- **Text Gray:** `#808080` - Secondary text

### Typography

All designs use **monospace fonts** to:
- Reflect the CLI/terminal nature of the project
- Honor the database/code aesthetic
- Pay homage to TempleOS's monospace interface

**Recommended fonts:**
- Courier New
- Monaco
- Consolas
- JetBrains Mono
- Fira Code

### Design Philosophy

The visual identity combines:
1. **Classical Architecture** - Temple columns, pediments
2. **Modern Technology** - Database symbols, data flow
3. **Retro Computing** - TempleOS colors, ASCII art
4. **Monospace Aesthetic** - Terminal-style typography

This reflects TempleDB's mission: bringing timeless database principles (the temple) to modern project management (the database).

---

## 📋 Usage Examples

### In Markdown

```markdown
<!-- Banner -->
![TempleDB](assets/banner.svg)

<!-- Logo -->
<img src="assets/logo.svg" width="200" alt="TempleDB Logo"/>

<!-- Icon -->
![Icon](assets/icon-small.svg)

<!-- TempleOS Tribute -->
<div align="center">
<img src="assets/templeos-tribute.svg" width="500" alt="TempleOS Tribute"/>
</div>
```

### In HTML

```html
<!-- Banner -->
<img src="assets/banner.svg" alt="TempleDB Banner" style="width: 100%; max-width: 800px;"/>

<!-- Logo (floating right) -->
<img src="assets/logo.svg" align="right" width="150" alt="TempleDB Logo"/>

<!-- Icon -->
<img src="assets/icon-small.svg" width="64" alt="TempleDB"/>
```

### As Link/Badge

```markdown
[![TempleDB](assets/icon-small.svg)](https://github.com/yourusername/templedb)
```

---

## 🔄 Converting to Other Formats

### PNG Export

```bash
# Using Inkscape
inkscape assets/logo.svg --export-png=assets/logo.png --export-width=200

# Using ImageMagick
convert -background none assets/logo.svg -resize 200x200 assets/logo.png

# For high-DPI displays (2x)
convert -background none assets/logo.svg -resize 400x400 assets/logo@2x.png
```

### Favicon

```bash
# Create 32x32 favicon
convert -background none assets/icon-small.svg -resize 32x32 favicon.ico

# Or multi-size favicon
convert -background none assets/icon-small.svg \
  -resize 16x16 -resize 32x32 -resize 48x48 -resize 64x64 \
  favicon.ico
```

### PDF Export

```bash
# Using Inkscape
inkscape assets/templeos-tribute.svg --export-pdf=assets/templeos-tribute.pdf

# Using rsvg-convert
rsvg-convert -f pdf -o assets/templeos-tribute.pdf assets/templeos-tribute.svg
```

---

## 🎯 Quick Reference

| Asset | Size | Purpose | Best For |
|-------|------|---------|----------|
| `banner.svg` | 800×200 | Headers, covers | README, docs, presentations |
| `logo.svg` | 200×200 | Main logo | Documentation, branding |
| `icon-small.svg` | 64×64 | Icons | CLI, favicons, badges |
| `templeos-tribute.svg` | 640×480 | Tribute art | README tribute section, exhibits |

---

## 📝 License

All visual assets in this directory are part of the TempleDB project and follow the same license.

---

## 🙏 Attribution

**Design Philosophy:**
- Inspired by TempleOS and Terry A. Davis
- Temple architecture symbolism
- Database/technology iconography
- Retro computing aesthetics

**TempleOS Color Palette:**
- Based on the authentic 16-color VGA palette used by Terry Davis in TempleOS
- A tribute to simplicity and first principles

---

*"An operating system is a temple."* - Terry A. Davis

**May these visuals honor Terry's legacy and the spirit of TempleOS.**
