# 3.図・表・数式｜Figure, Table, Equation
文責：堀江和正

[English Version](README_en.md)

---

## はじめに

情報科学の論文に，
- 図
- 表
- 数式

は付き物です．  
ここでは，これらの挿入方法と「参照番号」について説明します．

---

## 図の挿入方法

>[!Note]
>ここでは，授業で用いているシステム（platex + dvipdfmx）に合わせた説明をしています．
>使用するシステム構成によっては，図として利用できるファイル形式が異なる場合があります．

まずは挿入する図のファイルを作成してください．利用できるファイル形式は，
- `.eps`
- `.pdf`
- `.png`
- `.jpg`

です．ベクター画像（グラフなど）には`.pdf`を，ラスタ画像（写真など）には`.png`を用いることを推奨します．

本文中で図を挿入する際は，

```latex
\begin{figure}[htbp]
  \centering
  \includegraphics[width=0.8\linewidth]{figures/sample.png}
  \caption{サンプル図：〇〇の関係を示すグラフ}
\end{figure}
```

のように記述します．  
各行の意味は，
- `\begin{figure}`: [htbp]	図を挿入する環境を開始します。[htbp]は配置の優先度（here / top / bottom / page）を指定します。
- `\centering`: 図を中央寄せにします。
- `\includegraphics`:	画像ファイルを読み込みます。width=0.8\linewidthは本文幅の8割の大きさに指定しています。
  {}の中には，読み込む画像ファイルの場所を指定しています．{figures/sample.png}の場合は，  
```
  作業ディレクトリ　┬　コンパイルしたい.texファイル  
                  └　figureディレクトリ　- sample.png
```
というファイル構造になっていることを想定しています．

- `\caption{...}`:	図のキャプション（タイトル）を付けます。

です．

**論文の場合，図のキャプションは図の下につけるのが標準です．**

## 表の挿入方法

本文中で表を挿入する際は，

```latex
\begin{table}[htbp]
  \centering
  \caption{実験条件の一覧}
  \begin{tabular}{lcc}
    \hline
    条件名 & 温度 [℃] & 時間 [min] \\
    \hline
    条件A & 25 & 30 \\
    条件B & 30 & 45 \\
    条件C & 35 & 60 \\
    \hline
  \end{tabular}
\end{table}
```

のように記述します．  
各行の意味は，

- `\begin{table}[htbp]`: 表を挿入する環境を開始します。（[htbp]は配置指定で、ここでも「here / top / bottom / page」の略）
- `\centering`: 表を中央寄せにします。
- `\caption{...}`: 表のキャプション（タイトル）を付けます。
- `\begin{tabular}{lcc}`: 列の配置を指定します。l=左寄せ、c=中央寄せ、r=右寄せ。ここでは3列構成です。
- `\hline`: 横線を引きます。
- 各行の中身: \& で列を区切り、行末に \\\\ を置きます。

です．

**表のキャプション（タイトル）は，表の上に載せるのが標準です．**

また，`\multirow`や`\multicolumn`を用いることで，より複雑な表を作成することもできます．  
[参考](https://www.overleaf.com/learn/latex/Tables)

## 図表のぶち抜き

2段組みの文書において，図表を書面の横一杯に挿入したいというケースがよくあります．  
（例：`main.pdf`の図2）

その場合は，  
`\begin{table}[htbp]`, `\begin{figure}[htbp]`  
を，それぞれ  

`\begin{table*}[htbp]`, `\begin{figure*}[htbp]`  

のようにアスタリスク（*）を付けることで段組みをぶち抜くことができます．

> [!Tip]
> 論文誌によっては「ぶち抜き禁止（1段幅に収めること）」が指定されている場合があります．  
> 投稿規定を必ず確認してください．

---

## 数式の挿入方法

数式は，`\begin{equation}~\end{equation}`や`\begin{eqnarray}~\end{eqnarray}`を使うことで挿入することができます．

例1）
```latex
\begin{equation}
E = mc^2
\end{equation}
```

`equation`には，数式を一つだけ入れることができます．

例2）

```latex
\begin{eqnarray}
a + b &=& c \\
x + y &=& z
\end{eqnarray}
```

`eqnarray`には，複数の数式を入れることができます．  
表と同じように，改行は`\\`を用い，`&`を用いることで複数式の位置合わせを行うことができます．

<details><summary>補足</summary>
 `amsmath` パッケージを使用している場合は，`\begin{align} ~ \end{align}` でより美しく式を整列できます．
</details>

### よく使う式の例

| 分類 | 表現例 | LaTeX コード | 備考 |
|:------|:------|:--------------|:------|
| **添字・インデックス** | $a_{i}$ | `a_{i}` | 添字（下付き） |
|  | $a^{n}$ | `a^{n}` | 累乗（上付き） |
|  | $x_{ij}$ | `x_{ij}` | 二重添字 |

| 分類 | 表現例 | LaTeX コード | 備考 |
|:------|:------|:--------------|:------|
| **四則演算・累乗** | $a + b = c$ | `a + b = c` | 足し算 |
|  | $a - b = c$ | `a - b = c` | 引き算 |
|  | $a \times b = c$ | `a \times b = c` | 掛け算（×） |
|  | $a \div b = c$ | `a \div b = c` | 割り算（÷） |
|  | $\frac{a}{b} = c$ | `\frac{a}{b} = c` | 分数 |
|  | $a^2 + b^2 = c^2$ | `a^2 + b^2 = c^2` | 累乗 |

| 分類 | 表現例 | LaTeX コード | 備考 |
|:------|:------|:--------------|:------|
| **関数の例** | $\sin \theta = \frac{y}{r}$ | `\sin \theta = \frac{y}{r}` | 三角関数 |
|  | $\cos \theta = \frac{x}{r}$ | `\cos \theta = \frac{x}{r}` | 三角関数 |
|  | $\tan \theta = \frac{y}{x}$ | `\tan \theta = \frac{y}{x}` | 三角関数 |
|  | $\log_{2} 8 = 3$ | `\log_{2} 8 = 3` | 対数関数 |
|  | $\max(x, y)$ | `\max(x, y)` | 最大値 |
|  | $\min(x, y)$ | `\min(x, y)` | 最小値 |
|  | $\sqrt{x^2 + y^2}$ | `\sqrt{x^2 + y^2}` | 平方根 |

| 分類 | 表現例 | LaTeX コード | 備考 |
|:------|:------|:--------------|:------|
| **微積分** | $\frac{dy}{dx} = 3x^2$ | `\frac{dy}{dx} = 3x^2` | 微分（分数形式） |
|  | $\int_0^1 x^2 dx = \frac{1}{3}$ | `\int_0^1 x^2 dx = \frac{1}{3}` | 積分（下限・上限あり） |
|  | $\lim_{x \to 0} \frac{\sin x}{x} = 1$ | `\lim_{x \to 0} \frac{\sin x}{x} = 1` | 極限 |
|  | $\sum_{i=1}^{n} i = \frac{n(n+1)}{2}$ | `\sum_{i=1}^{n} i = \frac{n(n+1)}{2}` | 総和 |
|  | $\prod_{i=1}^{n} a_i$ | `\prod_{i=1}^{n} a_i` | 積記号 |

| 分類 | 表現例 | LaTeX コード | 備考 |
|:------|:------|:--------------|:------|
| **ベクトル** | $\overline{AB}$ | `\overline{AB}` | 上線（ベクトルや区間） |
|  | $\vec{v}$ | `\vec{v}` | 矢印付きベクトル |
|  | $\vec{a} \cdot \vec{b} = \|\vec{a}\|\|\vec{b}\|\cos\theta$ | `\vec{a} \cdot \vec{b} = \|\vec{a}\|\|\vec{b}\|\cos\theta` | 内積（スカラー積） |
|  | $\vec{a} \times \vec{b} = \|\vec{a}\|\|\vec{b}\|\sin\theta\vec{n}$ | `\vec{a} \times \vec{b} = \|\vec{a}\|\|\vec{b}\|\sin\theta\vec{n}` | 外積（ベクトル積） |
|  | $\|\vec{v}\| = \sqrt{x^2 + y^2 + z^2}$ | `\|\vec{v}\| = \sqrt{x^2 + y^2 + z^2}` | ベクトルの大きさ（ノルム） |

| 分類 | 表現例 | LaTeX コード | 備考 |
|:------|:------|:--------------|:------|
| **行列** | <img width="536" height="261" alt="image" src="https://github.com/user-attachments/assets/e8b6c522-05a5-4c9c-9ddf-115b224414c4" /> |<img width="725" height="235" alt="image" src="https://github.com/user-attachments/assets/62d92035-ba45-478b-a8ec-5fda7ced30f3" /> | 角括弧付き行列 |
|  | $\det(A) = ad - bc$ | `\det(A) = ad - bc` | 行列式 |

* https://tex.stackexchange.com/questions/204621/matrix-in-latex より数式を一部引用．


### 文中で数式を使いたい場合

本文中で数式を使いたい場合は，`\begin{equation}~\end{equation}`ではなく，$マークを使ってください．  
例）`$a > 0$`の時，・・・

### 特殊文字

数式に使うような一部の文字には，
- すでにLaTeXのコマンド用に確保されてしまっている（"%"など）
- 通常の英字キーボードで出力するのが難しい（α, Σ）など

などの理由で簡単に表示できないものがあります．  
これらの「特殊文字」はコマンドを通じて表示することが可能です．

| 種類 | 記号 | LaTeX コマンド | 備考 |
|:------|:------:|:----------------|:------|
| **一般記号** | % | \% | コメント記号。通常はそのまま表示不可 |
|  | # | \# | コマンド引数記号 |
|  | $ | \$ | 数式モードの開始・終了記号 |
|  | & | \& | 表の列区切りに使われるため、直接は出せない |
|  | _ | \_ | 下付き添字（subscript）に使われる |
|  | ^ | \^{} | 上付き添字（superscript）に使われる |
|  | { } | \{ , \} | グルーピング用の括弧 |
|  | ~ | \~{} | チルダ（波線）を表示 |
|  | \\ | \textbackslash | バックスラッシュを表示 |
|  | < > | \textless , \textgreater | 不等号をそのまま出したい場合 |
|  | | | \textbar | 縦棒（パイプ）をそのまま出す |

| 種類 | 記号 | LaTeX コマンド | 備考 |
|:------|:------:|:----------------|:------|
| **ギリシャ文字（小文字）** | α | \alpha |  |
|  | β | \beta |  |
|  | γ | \gamma |  |
|  | δ | \delta |  |
|  | ε | \epsilon または \varepsilon |  |
|  | θ | \theta |  |
|  | λ | \lambda |  |
|  | μ | \mu |  |
|  | π | \pi |  |
|  | σ | \sigma |  |
|  | φ | \phi または \varphi |  |
|  | ω | \omega |  |

| 種類 | 記号 | LaTeX コマンド | 備考 |
|:------|:------:|:----------------|:------|
| **ギリシャ文字（大文字）** | Γ | \Gamma |  |
|  | Δ | \Delta |  |
|  | Θ | \Theta |  |
|  | Λ | \Lambda |  |
|  | Ξ | \Xi |  |
|  | Π | \Pi |  |
|  | Σ | \Sigma |  |
|  | Φ | \Phi |  |
|  | Ψ | \Psi |  |
|  | Ω | \Omega |  |

| 種類 | 記号 | LaTeX コマンド | 備考 |
|:------|:------:|:----------------|:------|
| **数学記号** | ± | \pm | プラスマイナス |
|  | × | \times | 掛け算記号 |
|  | ÷ | \div | 割り算記号 |
|  | ≠ | \neq | 不等号 |
|  | ≒ | \simeq | ほぼ等しい |
|  | ≡ | \equiv | 同値 |
|  | ≤ | \leq | 以下 |
|  | ≥ | \geq | 以上 |
|  | ∞ | \infty | 無限大 |
|  | ∑ | \sum | 総和記号 |
|  | ∫ | \int | 積分記号 |
|  | √ | \sqrt{} | 平方根 |
|  | → | \rightarrow | 右矢印 |
|  | ← | \leftarrow | 左矢印 |
|  | ↔ | \leftrightarrow | 両矢印 |
|  | ⇒ | \Rightarrow | 論理的含意 |
|  | ⇔ | \Leftrightarrow | 論理的同値 |

| 種類 | 記号 | LaTeX コマンド | 備考 |
|:------|:------:|:----------------|:------|
| **その他** | ° | ^\circ | 度数記号 |
|  | ℓ | \ell | 手書き風の小文字L |
|  | … | \ldots | 省略記号（横方向） |
|  | ⋯ | \cdots | 中央に配置されるドット |
|  | • | \bullet | 中黒（箇条書きなど） |

また，一部の数学記号（⊂, ⊃, ∈, ∉ など）は，
パッケージ`amssymb, amsmath`が必要になるものもあります．

## 参照番号とは？

図表や式には、識別のために番号（参照番号）が付けられます。
この参照番号を使うことで、本文中から特定の図や式を指し示すことができます。

例えば，`main.pdf`では参照番号を用いることでどの図を指しているのかを明確にしています．

例）図2 より，判定根拠が提示でき，かつ専門家の判断根拠と一致することが確認できた．
この"図2"が参照番号を利用している部分です．

このような参照番号は，LaTeX側で自動的に数字を割り当てることができます．
参照番号の利用には`\label{}`と`\ref{}`の2種類のコマンドを使用します．

例）  
**図・表の場合**
`\caption{~~~}`の直後に`\label{hogehoge}`を記述してください．  
その後，本文中で`\ref{hogehoge}`と書けば，自動的に図表番号に置き換わります．

<details><summary>例</summary>

```latex
\begin{figure}[htbp]
  \centering
  \includegraphics[width=0.8\linewidth]{figures/sample.png}
  \caption{サンプル図：〇〇の関係を示すグラフ}
  \label{fig:samples} $←ここに入れる 
\end{figure}

サンプル図\ref{fig:samples}より，～～～
```

</details>

**数式の場合**
式の直後に`\label{hogehoge}`を記述してください．

<details><summary>例</summary>

```latex
\begin{equation}
  f(x) = \lim_{x\to\infty} \int_0^x g(t)\,dt \label{eq:f-inf} $←ここに入れる
\end{equation}
である。\ref{eq:f-inf}式はすなわち，〇〇を意味する。
```

</details>

## ここまで理解したら，

ここまでで作成した`main.tex`に，図と表を加え，お手本の`main.pdf`に近づけましょう．  
図のファイルは本ディレクトリで配布しています．  
また，文中の??となっている部分は，元々図・表・数式の参照番号が入っていた部分です．  
`\label{}`,`ref{}`を用いて，適切な参照番号を割り振ってください．

[次](https://github.com/kdesleep-code/Info-Literacy-Latex-Exercise/blob/main/4.%E5%8F%82%E8%80%83%E6%96%87%E7%8C%AE%EF%BD%9CReferences/README.md)
