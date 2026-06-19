# 2.文書構造｜Document Structure
文責：堀江和正

[English Version](README_en.md)

---

## はじめに

一般的な論文は，

1. タイトルと著者名
2. Abstract（＝概要）
3. Introduction（＝背景・目的・既存研究の説明）
4. 提案手法
5. 評価実験
6. 考察
7. Conclusion（＝まとめ）

で構成されます．  
本授業で用いているお手本（[main.pdf](../main.pdf)）もだいぶ内容を端折っていますが，これに準じています．

どの文章が，どの構成要素なのかを明確にするためには「章」を分けるのが一般的です．

本稿では，まずLaTeX文書で「章」や「節」を作る方法を説明します．

---

## 「章」「節」の作り方

LaTeX文書で章や節を作る際には，以下のコマンドが利用可能です．

| コマンド               | 階層        | 用途の例                 |
| ------------------ | --------- | -------------------- |
| `\section{}`       | 第1階層（章）   | 「1. はじめに」「2. 提案手法」など |
| `\subsection{}`    | 第2階層（節）   | 「2.1 モデル構成」など        |
| `\subsubsection{}` | 第3階層（小節）  | 「2.1.1 Attention層」など |
| `\paragraph{}`     | 第4階層（段落）  | さらに細かい項目説明に使用        |
| `\subparagraph{}`  | 第5階層（小段落） | 通常はほとんど使わない          |

<details><summary>補足</summary>`documentclass[book]`では`\chapter()`も利用できます．</details>

例えば，

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

をLaTeXコンパイルすると

<img width="564" height="678" alt="image" src="https://github.com/user-attachments/assets/dd7e4998-9025-4cec-ac09-670d7a3ba94a" />

のようになります．

章の「番号」はLaTeX側で自動的に割り振りが行われます（便利！）．  
番号をつけたくない場合は，`\section*{}`のようにアスタリスクをつければOKです．


### Abstractは特別扱い

特殊な「章」としてAbstractがあり，`\section{}`ではなく，

```latex
\begin{abstract} 

～～ここにAbstractを書く．～～

\end{abstract}
```
で記述します．

これは，Abstractが本文から独立して表示・掲載されることが多いためです．  
例えば，本文は2段組みだけどAbstractは1段組み，といった論文誌も多くあります．

### 目次を作りたい場合

本文の任意の場所で，

```latex
\tableofcontents
```

と入力すると，目次が作成できます．  
修士論文執筆時など，長い論文を書く時には利用してください．

---

## 箇条書き（リスト）の作り方

文章をわかりやすくするためには，章立てだけでなく箇条書きも有効です．  
LaTeXでは、箇条書きを作るために次の3種類がよく使われます。

|  | 表示形式 | 用途の例 |
|---------|-----------|----------|
| `\begin{itemize}~\end{itemize}` | 「・」のような黒丸付きリスト | 一般的な箇条書き |
| `\begin{enumerate}~\end{enumerate}` | 「1.」「2.」などの番号付きリスト | 手順や順序のある説明 |
| `\begin{description}~\end{description}` | 用語＋説明の組み合わせ | 用語解説や略語の定義など |

各項目は`\item (内容)`と記述します．

---

### 例1：通常の箇条書き（itemize）

```latex
\begin{itemize}
    \item 睡眠は健康維持に不可欠である．
    \item 深い睡眠では成長ホルモンが分泌される．
    \item 睡眠不足は集中力の低下を招く．
\end{itemize}
```

出力結果：

- 睡眠は健康維持に不可欠である．  
- 深い睡眠では成長ホルモンが分泌される．  
- 睡眠不足は集中力の低下を招く．  

---

### 例2：番号付きリスト（enumerate）

```latex
\begin{enumerate}
    \item データの前処理を行う．
    \item モデルを学習する．
    \item 評価指標を算出する．
\end{enumerate}
```

出力結果：

1. データの前処理を行う．  
2. モデルを学習する．  
3. 評価指標を算出する．  

---

### 例3：説明付きリスト（description）

```latex
\begin{description}
    \item[REM睡眠] 眼球運動が活発で夢を見やすい睡眠状態．
    \item[ノンレム睡眠] 体が深く休息している状態．
\end{description}
```

出力結果：

**REM睡眠**　眼球運動が活発で夢を見やすい睡眠状態．  
**ノンレム睡眠**　体が深く休息している状態．  

---

### ネスト（入れ子）も可能

箇条書きの中にさらに箇条書きを作ることもできます。

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

### まとめ

- 順序がない場合 → `itemize`  
- 順序がある場合 → `enumerate`  
- 用語の説明など → `description`

目的に合わせて上手に使い分けましょう．

## ここまで理解したら，
本ディレクトリの`body.txt`に，章立て前の本文が入っています．  
これを`main.tex`にコピペし，`main.pdf`と同じになるように章立てを行ってください．

[次へ](https://github.com/kdesleep-code/Info-Literacy-Latex-Exercise/blob/main/3.%E5%9B%B3%E3%83%BB%E8%A1%A8%E3%83%BB%E6%95%B0%E5%BC%8F%EF%BD%9CFigures%2C%20Tables%2C%20and%20Equations/README.md)




