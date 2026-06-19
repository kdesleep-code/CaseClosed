# 5.発展課題｜Advanced Exercise
文責：堀江和正

[English Version](README_en.md)

---

> [!Note]
> この章は**発展課題＝オプション**です．  
> 本章の内容は「成績評価の範囲外」です．

ここでは，**学会や出版社が配布しているLaTeXテンプレート:スタイルファイル**の導入方法を説明します．  
論文誌ごとに指定が異なりますが，基本的な流れは共通です．

## 学会スタイルファイルの導入手順

- 学会公式サイトからテンプレートをダウンロード  
多くの学会では「Author Kit」や「LaTeX Template」という名前で .cls（クラスファイル）や .bst（参考文献スタイル）を配布しています。  
例）IEEE, Springer, Elsevier, ACM, Nature など。

- 展開して同じディレクトリに配置  
たとえば IEEEtran.cls を使用する場合、main.tex と同じディレクトリに配置してください。  
そのうえで冒頭を以下のように書き換えます。  

```latex
\documentclass[conference]{IEEEtran}  % または journal, transmag など
\usepackage[dvipdfmx]{graphicx}
```

- よく使われる学会テンプレート（公式配布ページ）

| 学会・出版社           | LaTeXテンプレート配布ページ                                                                                            |
| :--------------- | :---------------------------------------------------------------------------------------------------------- |
| IEEE             | [IEEE Author Center: LaTeX Templates](https://www.ieee.org/conferences/publishing/templates.html)           |
| ACM              | [ACM Master Article Template](https://www.acm.org/publications/taps/word-template-workflow)                 |
| Springer         | [Springer LaTeX Templates (LNCS)](https://www.springernature.com/gp/authors/campaigns/latex-author-support) |
| Elsevier         | [Elsevier Template for LaTeX](https://www.elsevier.com/authors/tools-and-resources/latex-templates)         |
| Nature Portfolio | [Nature LaTeX Template](https://www.nature.com/nature/for-authors/latex)                                    |

>[!Note]
>テンプレートによっては、特定のパッケージが禁止されていることがあります（例：hyperrefやamsmathの再定義）。  
>投稿前に必ず「Author Guidelines」を確認し、テンプレート外のパッケージを削除してから提出してください。  
>参考文献のスタイル .bst も、学会ごとに指定されているものを使用してください。  


## そのほか，知っていると便利な操作について
>[!Note]
>英語ページです．適宜翻訳して読んでください．

### カスタムコマンド
[https://www.physicsread.com/latex-newcommand/](https://www.physicsread.com/latex-newcommand/)

### Table関連: Multirow, MultiColumnなど
[https://www.overleaf.com/learn/latex/Tables](https://www.overleaf.com/learn/latex/Tables)

### 太字，イタリック，アンダーライン
[https://www.overleaf.com/learn/latex/Bold%2C_italics_and_underlining](https://www.overleaf.com/learn/latex/Bold%2C_italics_and_underlining)

### 図関連: Subfigure（複数の図を並列に並べる）など
[https://www.overleaf.com/learn/latex/Positioning_images_and_tables#Positioning_images](https://www.overleaf.com/learn/latex/Positioning_images_and_tables#Positioning_images)

>[!Important]
>[Overleafのドキュメンテーション](https://www.overleaf.com/learn)には，様々なコマンドの説明が掲載されています．  
>GPT等を用いて特定の整形をするためのコマンドを教えてもらうのもよい手でしょう．

