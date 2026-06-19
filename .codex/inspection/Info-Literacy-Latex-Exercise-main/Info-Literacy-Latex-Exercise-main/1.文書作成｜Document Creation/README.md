# 1.文書作成｜Document Creation
文責：堀江和正

[English Version](README_en.md)

---

## まずは，Coins計算機上でLaTeXコンパイルと完成品のダウンロードをやってみる．

まず，本ディレクトリの`main.tex`を自分のPCにダウンロードし，SCPを通じてcoins計算機に転送してみましょう．  
自分のPCから以下のコマンドでファイルが転送されます．

```Bash
scp ./main.tex <UserID>@<Coins IP>:~
```

これ以降，ほとんど全ての作業はCoins計算機上で実行します．

まずはファイルの中身を確認しましょう．

```Bash
cat ./main.tex
```

すると，以下の内容が表示されるはずです．

```latex

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

このファイルは，タイトルと少しの本文を加えた最小構成のTexファイルです．  
早速，コンパイルしてみましょう．コンパイルのコマンドは以下です．

```Bash
platex main.tex
dvipdfmx main.dvi
```

実行すると`main.pdf`というファイルが手に入るはずです．  
scpで実際にダウンロードしてみましょう．

自分のPCの端末から，

```Bash
scp <UserID>@<Coins IP>:~/main.pdf . 
```

を入力することで，端末の現在のディレクトリにmain.pdfが保存されます．

## 具体的に，あのTexファイルには何が書かれていたの？

``` latex
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

Texファイルには大きく，**コマンド**と**文章**の２つが含まれています．
- コマンド：LaTeXソフトに指示を与えるための文．`\`から始まる．
- 文章：文書の中で表示したい文そのもの．

構造的には，**Header**と**Body**に分割できます．

- Header: pdfには直接表示されない領域．コンパイルの設定コマンドを書くところ．  
  上記の例だと，`\documentclass[twocolumn,11pt]{jsarticle}` ~ `\date{\today}`の領域．
- Body: pdfに直接表示されるものを書くところ．本文．  
  上記の例だと，`\begin{document}` ~ `\end{document}`で囲まれた部分．


### Headerの各行の意味

- `\documentclass[twocolumn,11pt]{jsarticle}`  
  `\documentclass`は，「文章の型」を決めるためのコマンドです．  
  このケースだと，2段組み(`twocolumn`)，デフォルトフォントサイズ11pt(`11pt`)，日本語の文書(`jsarticle`)であることを示しています．
  <details><summary>他には，</summary>
    
  **英文**  
  | クラス名 | 用途・特徴 | 備考 |
  |-----------|-------------|------|
  | `article` | 一般的な論文・短いレポート・技術文書 | 最も汎用的。セクション単位の構造（chapterなし） |
  | `report` | 長めのレポートや卒論・修論など | `chapter`単位が使える。`article`の上位版 |
  | `book` | 書籍・長大な文書 | 章・節構造＋目次・索引などに対応 |
  | `letter` | 手紙・書簡 | アドレスや署名などの専用環境あり |
  
  **和文**
  | クラス名 | 用途・特徴 | 備考 |
  |-----------|-------------|------|
  | `jsarticle` | 一般的な日本語論文・レポート | upLaTeX/pLaTeX対応 |
  | `jsreport` | 長いレポート・卒論・修論向け | `chapter`が使用可能 |
  | `jsbook` | 書籍向け | |
   
  **レイアウト関連**
  | オプション | 意味・説明 | 備考 |
  |-------------|-------------|------|
  | `onecolumn` | 1段組（デフォルト） | |
  | `twocolumn` | 2段組にする | 学会論文形式でよく使用 |
  | `oneside` | 片面印刷用（デフォルト） | |
  | `twoside` | 両面印刷用 | 書籍など |
  | `openright` | 章を右ページから開始 | `book`で使用 |
  | `openany` | 章を任意のページから開始 | |

  **紙サイズ**
  | オプション | 内容 | 備考 |
  |-------------|--------|------|
  | `a4paper` | A4サイズ | 日本・欧州標準 |
  | `b5paper` | B5サイズ | 日本の論文誌で多い |
  | `letterpaper` | USレターサイズ | 米国標準 |
  | `landscape` | 横向き | |
  | `portrait` | 縦向き（デフォルト） | |

  などがあります．
  </details>
- `\usepackage[hogehoge]{hogehoge}`  
  LaTeXシステムが標準で対応していないコマンドをロードするための設定です．  
  種類があまりにも多いのでここでは割愛します．
  
- `\geometry{margin=20mm}`  
  紙面の断ち切りを20mmに設定する．

- `\title{Sleep-CAM：説明可能な睡眠ステージ自動判定}`  
  文章のタイトルを設定
- `\author{堀江和正とゆかいな仲間たち\\筑波大学}`  
  著者名を設定．`\\`は改行を強制するコマンドです．
- `\date{\today}`  
  日付を設定

などを行っています．

雑誌投稿論文や国際会議論文，卒業論文などではこれらの情報が書かれたテンプレートファイルが配られるケースがほとんどです．  
`\usepackage`コマンド以外は覚えていなくても問題ありません．


### Bodyの各行の意味

- `\begin{document}`: ここからBodyが始まりますよ，と宣言するコマンド．  
  `\begin{hogehoge}`はよく見るコマンド．すべてここからhogehogeが始まりますよ，という意味．
- `\maketitle`: ここにタイトルを入れてください，という意味のコマンド．
- 睡眠ステージ・・・・・: 本文．
- `\end{document}`: ここでBodyが終わりましたよ，と宣言するコマンド．  
  `\end{hogehoge}`は（以下略）．


### ここまで理解したら，

著者名をあなたの名前に変更してもう一度コンパイル＆ダウンロードしてみましょう．  
著者名が「堀江和正とゆかいな仲間たち」からあなたの名前になっていることを確認してください．

[次へ](https://github.com/kdesleep-code/Info-Literacy-Latex-Exercise/blob/main/2.%E6%96%87%E6%9B%B8%E6%A7%8B%E9%80%A0%EF%BD%9CDocument%20Structure/README.md)



