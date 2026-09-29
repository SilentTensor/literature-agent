# 自绘控件（C# 定义，供启动器.ps1 引用）
#
# 为什么用 C# 而不是 PowerShell 的 class：
#   PowerShell 在"解析阶段"就要求 class 的基类和字段类型已经存在，而
#   Add-Type 是"运行阶段"才加载 System.Windows.Forms。结果
#   `class CardPanel : System.Windows.Forms.Panel` 会直接报
#   "Unable to find type [System.Windows.Forms.Panel]"。
#   用 Add-Type 定义 C# 类型时可以显式 --ReferencedAssemblies，绕开这个限制。

$uiCode = @'
using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Text;
using System.Windows.Forms;

public static class Rounded {
    public static GraphicsPath Path(int x, int y, int w, int h, int r) {
        GraphicsPath p = new GraphicsPath();
        if (r <= 0 || w <= 0 || h <= 0) { p.AddRectangle(new Rectangle(x, y, w, h)); return p; }
        int d = r * 2;
        if (d > w) d = w;
        if (d > h) d = h;
        p.AddArc(x, y, d, d, 180, 90);
        p.AddArc(x + w - d, y, d, d, 270, 90);
        p.AddArc(x + w - d, y + h - d, d, d, 0, 90);
        p.AddArc(x, y + h - d, d, d, 90, 90);
        p.CloseFigure();
        return p;
    }
}

// 圆角卡片：白底（或渐变）+ 细描边
public class CardPanel : Panel {
    public int Radius = 10;
    public Color Fill = Color.White;
    public Color Stroke = Color.FromArgb(228, 231, 236);
    public bool UseGradient = false;
    public Color GradTop = Color.White;
    public Color GradBot = Color.White;

    public CardPanel() {
        SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.UserPaint |
                 ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw, true);
        BackColor = Color.Transparent;
    }

    protected override void OnPaint(PaintEventArgs e) {
        Graphics g = e.Graphics;
        g.SmoothingMode = SmoothingMode.AntiAlias;
        int w = Width - 1, h = Height - 1;
        if (w <= 0 || h <= 0) return;
        using (GraphicsPath p = Rounded.Path(0, 0, w, h, Radius)) {
            if (UseGradient) {
                using (LinearGradientBrush b = new LinearGradientBrush(
                           new Rectangle(0, 0, Math.Max(w, 1), Math.Max(h, 1)), GradTop, GradBot, 90f))
                    g.FillPath(b, p);
            } else {
                using (SolidBrush b = new SolidBrush(Fill)) g.FillPath(b, p);
                if (Stroke.A > 0) using (Pen pen = new Pen(Stroke, 1f)) g.DrawPath(pen, p);
            }
        }
    }
}

// 扁平圆角按钮，带 hover / pressed 三态
public class FlatButton : Button {
    public int Radius = 6;
    public Color Normal = Color.White;
    public Color HoverColor = Color.White;
    public Color DownColor = Color.White;
    public Color TextColor = Color.FromArgb(32, 36, 44);
    public bool Outlined = false;
    public Color OutlineColor = Color.FromArgb(214, 219, 226);
    private bool hov = false, dwn = false;

    public FlatButton() {
        SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.UserPaint |
                 ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw |
                 ControlStyles.SupportsTransparentBackColor, true);
        FlatStyle = FlatStyle.Flat;
        FlatAppearance.BorderSize = 0;
        BackColor = Color.Transparent;
        Cursor = Cursors.Hand;
        Font = new Font("Microsoft YaHei UI", 9f);
        UseVisualStyleBackColor = false;
    }

    protected override void OnMouseEnter(EventArgs e) { hov = true; Invalidate(); base.OnMouseEnter(e); }
    protected override void OnMouseLeave(EventArgs e) { hov = false; dwn = false; Invalidate(); base.OnMouseLeave(e); }
    protected override void OnMouseDown(MouseEventArgs e) { dwn = true; Invalidate(); base.OnMouseDown(e); }
    protected override void OnMouseUp(MouseEventArgs e) { dwn = false; Invalidate(); base.OnMouseUp(e); }

    protected override void OnPaint(PaintEventArgs e) {
        Graphics g = e.Graphics;
        g.SmoothingMode = SmoothingMode.AntiAlias;
        g.TextRenderingHint = TextRenderingHint.ClearTypeGridFit;
        int w = Width - 1, h = Height - 1;
        if (w <= 0 || h <= 0) return;

        Color col = dwn ? DownColor : (hov ? HoverColor : Normal);
        using (GraphicsPath p = Rounded.Path(0, 0, w, h, Radius)) {
            using (SolidBrush b = new SolidBrush(col)) g.FillPath(b, p);
            if (Outlined) using (Pen pen = new Pen(OutlineColor, 1f)) g.DrawPath(pen, p);
        }
        using (StringFormat f = new StringFormat()) {
            f.Alignment = StringAlignment.Center;
            f.LineAlignment = StringAlignment.Center;
            using (SolidBrush tb = new SolidBrush(TextColor))
                g.DrawString(Text, Font, tb, new RectangleF(0, 0, Width, Height), f);
        }
    }
}

// 圆形状态点，带外圈光晕
public class StatusDot : Control {
    private Color dot = Color.Gray;
    public Color DotColor {
        get { return dot; }
        set { dot = value; Invalidate(); }
    }

    public StatusDot() {
        SetStyle(ControlStyles.AllPaintingInWmPaint | ControlStyles.UserPaint |
                 ControlStyles.OptimizedDoubleBuffer |
                 ControlStyles.SupportsTransparentBackColor, true);
        BackColor = Color.Transparent;
    }

    protected override void OnPaint(PaintEventArgs e) {
        Graphics g = e.Graphics;
        g.SmoothingMode = SmoothingMode.AntiAlias;
        if (Width < 4 || Height < 4) return;
        using (SolidBrush hb = new SolidBrush(Color.FromArgb(70, dot)))
            g.FillEllipse(hb, 0, 0, Width - 1, Height - 1);
        int pad = (int)(Width * 0.28);
        int s = Width - pad * 2 - 1;
        if (s < 1) s = 1;
        using (SolidBrush b = new SolidBrush(dot))
            g.FillEllipse(b, pad, pad, s, s);
    }
}
'@

Add-Type -ReferencedAssemblies System.Windows.Forms, System.Drawing -TypeDefinition $uiCode -ErrorAction Stop
