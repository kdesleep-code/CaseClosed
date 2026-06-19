# 1. Document Creation  
Author: Kazumasa Horie

[日本語版](README.md)

---

## Let's start by compiling LaTeX and downloading the finished PDF on the Coins computer

First, download the `main.tex` file in this directory to your own PC, and transfer it to the Coins computer via SCP.  
From your local PC, execute the following command:

```Bash
scp ./main.tex <UserID>@<Coins IP>:~
```

From this point onward, almost all operations will be performed on the Coins computer.

First, check the contents of the file:

```Bash
cat ./main.tex
```

You should see the following:

```LaTex
\documentclass[twocolumn,11pt]{jsarticle}
\usepackage[dvipdfmx]{graphicx}
\usepackage[dvipdfmx,bookmarks=true,colorlinks=true,linkcolor=blue,urlcolor=blue,citecolor=blue]{hyperref}
\usepackage{amsmath,amssymb}
\usepackage{booktabs}
\usepackage{geometry}
\usepackage{cite}
\geometry{margin=20mm}

\title{Sleep-CAM：説明可能な睡眠ステージ自動判定}
\author{堀江和正とゆかいな仲間たち\\筑波大学}
\date{\today}

\begin{document}
\maketitle

睡眠ステージ（W, REM, N1, N2, N3）は睡眠医療において重要であり，従来は専門家がPSG（EEG/EOG/EMG）から特徴波を同定して目視判定する。
自動化の研究は発展しているが，臨床での信頼を得るには，どの信号のどの部分を根拠に判定したかを提示できる説明可能性が鍵である。

\end{document}
```

This file is a minimal LaTeX document containing only a title and a short paragraph.  
Now, let’s compile it using the following commands:

```Bash
platex main.tex
dvipdfmx main.dvi
```

Once executed, you should obtain a file named `main.pdf`.  
Next, download it to your local PC using `scp`:

```Bash
scp <UserID>@<Coins IP>:~/main.pdf .
```

This will save `main.pdf` in your current local directory.

---

## What exactly is written in that LaTeX file?

```LaTex
\documentclass[twocolumn,11pt]{jsarticle}
\usepackage[dvipdfmx]{graphicx}
\usepackage[dvipdfmx,bookmarks=true,colorlinks=true,linkcolor=blue,urlcolor=blue,citecolor=blue]{hyperref}
\usepackage{amsmath,amssymb}
\usepackage{booktabs}
\usepackage{geometry}
\usepackage{cite}
\geometry{margin=20mm}

\title{Sleep-CAM：説明可能な睡眠ステージ自動判定}
\author{堀江和正とゆかいな仲間たち\\筑波大学}
\date{\today}

\begin{document}
\maketitle

睡眠ステージ（W, REM, N1, N2, N3）は睡眠医療において重要であり，従来は専門家がPSG（EEG/EOG/EMG）から特徴波を同定して目視判定する。
自動化の研究は発展しているが，臨床での信頼を得るには，どの信号のどの部分を根拠に判定したかを提示できる説明可能性が鍵である。

\end{document}
```

A LaTeX file consists of two main parts: **commands** and **text**.  
- **Commands**: Instructions for the LaTeX system, beginning with a backslash `\`.  
- **Text**: The actual content that appears in the final document.

Structurally, it is divided into two sections: **Header** and **Body**.  
- **Header**: Configuration area not directly displayed in the PDF.  
  In this example, from `\documentclass` to `\date`.  
- **Body**: The main content displayed in the PDF, enclosed between `\begin{document}` and `\end{document}`.

---

### Meaning of each line in the Header

- `\documentclass[twocolumn,11pt]{jsarticle}`  
  This command specifies the “document class,” defining the overall format.  
  Here, it means a **two-column layout** (`twocolumn`), **11pt font size** (`11pt`), and **Japanese article format** (`jsarticle`).

  <details><summary>Other common classes:</summary>

  **English classes**  
  | Class | Purpose | Notes |
  |--------|----------|--------|
  | `article` | General short papers or technical reports | No chapters |
  | `report` | Long reports, theses | Supports `chapter` |
  | `book` | Books | Full sectioning and indices |
  | `letter` | Letters | Specialized structure for addresses/signatures |

  **Japanese classes**  
  | Class | Purpose | Notes |
  |--------|----------|--------|
  | `jsarticle` | General Japanese articles | For upLaTeX/pLaTeX |
  | `jsreport` | Theses and long reports | Supports `chapter` |
  | `jsbook` | Books |  |

  **Layout options**  
  | Option | Description | Notes |
  |---------|--------------|--------|
  | `onecolumn` | Single column (default) |  |
  | `twocolumn` | Two-column layout | Common in conference papers |
  | `oneside` | Single-sided printing | Default |
  | `twoside` | Double-sided printing | Used for books |
  | `openright` | Start chapters on right pages | For books |
  | `openany` | Start chapters anywhere |  |

  **Paper size**  
  | Option | Description | Notes |
  |---------|--------------|--------|
  | `a4paper` | A4 size | Standard in Japan/Europe |
  | `b5paper` | B5 size | Common in Japanese journals |
  | `letterpaper` | US letter size | Standard in the U.S. |
  | `landscape` | Horizontal layout |  |
  | `portrait` | Vertical layout (default) |  |

  </details>

- `\usepackage[hogehoge]{hogehoge}`  
  Loads additional LaTeX packages for extended functionality.

- `\geometry{margin=20mm}`  
  Sets the page margins to 20 mm.

- `\title{Sleep-CAM：説明可能な睡眠ステージ自動判定}`  
  Defines the title of the document.

- `\author{堀江和正とゆかいな仲間たち\\筑波大学}`  
  Defines the author name(s). `\\` enforces a line break.

- `\date{\today}`  
  Displays the current date.

In practice, academic journals, conferences, and universities provide predefined LaTeX templates.  
Thus, except for `\usepackage`, you rarely need to memorize these commands.

---

### Meaning of each line in the Body

- `\begin{document}` — Declares the beginning of the document body.  
- `\maketitle` — Inserts the title section.  
- The Japanese sentences — Main text.  
- `\end{document}` — Marks the end of the document.

---

### Once you understand this

Try changing the author name from  
“堀江和正とゆかいな仲間たち”  
to your own name, recompile, and download again.  
Confirm that the author name has been updated correctly.

[Next](https://github.com/kdesleep-code/Info-Literacy-Latex-Exercise/blob/main/2.%E6%96%87%E6%9B%B8%E6%A7%8B%E9%80%A0%EF%BD%9CDocument%20Structure/README_en.md)  
