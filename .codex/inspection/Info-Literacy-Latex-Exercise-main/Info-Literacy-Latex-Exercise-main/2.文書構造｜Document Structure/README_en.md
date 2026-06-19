# 2. Document Structure  
Author: Kazumasa Horie  

[日本語版](README.md)

---

## Introduction

A typical academic paper consists of the following sections:

1. Title and Author
2. Abstract
3. Introduction (Background, Purpose, Related Works)
4. Proposed Method
5. Experiments / Evaluation
6. Discussion
7. Conclusion

The example document used in this course ([main.pdf](../main.pdf)) follows this structure, though simplified for instructional purposes.

To make it clear which part of your text belongs to which element of the paper, it is common to divide your document into **sections**.

This chapter explains how to create *sections* and *subsections* in LaTeX.

---

## Creating Sections and Subsections

In LaTeX, the following commands are used to define chapters and sections.

| Command | Hierarchy | Example Usage |
|----------|------------|----------------|
| `\section{}` | Level 1 (Section) | “1. Introduction”, “2. Proposed Method” |
| `\subsection{}` | Level 2 (Subsection) | “2.1 Model Structure” |
| `\subsubsection{}` | Level 3 (Subsubsection) | “2.1.1 Attention Layer” |
| `\paragraph{}` | Level 4 (Paragraph) | For more detailed explanations |
| `\subparagraph{}` | Level 5 (Subparagraph) | Rarely used |

<details><summary>Note</summary>`documentclass[book]` allows the use of `\chapter{}` as well.</details>

For example:

```latex
\section{考察}
GAPは時刻情報を平均化するため，AASM規則の一部（波形の出現タイミングや割合）を完全には再現できない。
一方でパラメータ削減・学習安定化の効果があり，全体精度では有利に働く。
孤立エポック（遷移付近）や覚醒イベントへの対処は今後の改良点である。

\section{まとめ}
本研究では、推論機構を備えた新しい睡眠ステージ自動判定モデル「Sleep-CAM」を提案した。
提案法は、判定根拠となる信号区間を明示し、α波・紡錘波・REM眼球運動・徐波など、専門家が用いる特徴波と一致することを確認した。
また、86.9\%の精度を達成し、既存法および専門家間一致を上回った。
```

When compiled, it will look like this:

<img width="564" height="678" alt="image" src="https://github.com/user-attachments/assets/dd7e4998-9025-4cec-ac09-670d7a3ba94a" />

The section numbers are automatically assigned by LaTeX — very convenient!  
If you want to remove the numbering, add an asterisk like `\section*{}`.

---

### Abstract Is a Special Case

The *Abstract* section is treated differently from the rest of the document.  
Instead of using `\section{}`, it is written as follows:

```latex
\begin{abstract} 

～～ここにAbstractを書く．～～

\end{abstract}
```

This is because the abstract is often displayed independently from the main text.  
For example, some journals use a **two-column layout** for the main body but a **single-column layout** for the abstract.

---

### Creating a Table of Contents

To automatically generate a table of contents, insert the following command anywhere in your document:

```latex
\tableofcontents
```

This is especially useful when writing long documents such as a master’s thesis.

---

## Creating Lists (Itemization)

In addition to structuring your text with sections, you can make your document more readable by using lists.  
LaTeX provides three main types of lists:

| Environment | Display Format | Typical Usage |
|--------------|----------------|----------------|
| `\begin{itemize}~\end{itemize}` | Bulleted list | General unordered lists |
| `\begin{enumerate}~\end{enumerate}` | Numbered list (1., 2., 3., …) | Step-by-step explanations |
| `\begin{description}~\end{description}` | Term–Description pairs | Glossaries or term definitions |

Each item is written using `\item (content)`.

---

### Example 1: Bulleted List (itemize)

```latex
\begin{itemize}
    \item 睡眠は健康維持に不可欠である．
    \item 深い睡眠では成長ホルモンが分泌される．
    \item 睡眠不足は集中力の低下を招く．
\end{itemize}
```

Output:

- 睡眠は健康維持に不可欠である．  
- 深い睡眠では成長ホルモンが分泌される．  
- 睡眠不足は集中力の低下を招く．  

---

### Example 2: Numbered List (enumerate)

```latex
\begin{enumerate}
    \item データの前処理を行う．
    \item モデルを学習する．
    \item 評価指標を算出する．
\end{enumerate}
```

Output:

1. データの前処理を行う．  
2. モデルを学習する．  
3. 評価指標を算出する．  

---

### Example 3: Descriptive List (description)

```latex
\begin{description}
    \item[REM睡眠] 眼球運動が活発で夢を見やすい睡眠状態．
    \item[ノンレム睡眠] 体が深く休息している状態．
\end{description}
```

Output:

**REM睡眠** — 眼球運動が活発で夢を見やすい睡眠状態．  
**ノンレム睡眠** — 体が深く休息している状態．  

---

### Nested Lists

You can also nest lists within other lists.

```latex
\begin{itemize}
    \item データセット
        \begin{itemize}
            \item EDF形式の脳波データ
            \item CSV形式の睡眠日誌
        \end{itemize}
    \item 評価指標
        \begin{itemize}
            \item 精度（Accuracy）
            \item Cohen’s κ係数
        \end{itemize}
\end{itemize}
```

---

### Summary

- Use `itemize` for unordered lists.  
- Use `enumerate` for ordered lists.  
- Use `description` for term-based explanations.  

Choose the appropriate type depending on the purpose of your text.

---

## Next Step

Now that you understand how to structure and format a LaTeX document,  
open `body.txt` in this directory and copy its content into `main.tex`.  
Then, structure it properly so that it matches the example in `main.pdf`.

[Next](https://github.com/kdesleep-code/Info-Literacy-Latex-Exercise/blob/main/3.%E5%9B%B3%E3%83%BB%E8%A1%A8%E3%83%BB%E6%95%B0%E5%BC%8F%EF%BD%9CFigures%2C%20Tables%2C%20and%20Equations/README_en.md)
