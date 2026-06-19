# 3. Figures, Tables, and Equations  
Author: Kazumasa Horie  

[日本語版](README.md)

---

## Introduction

In academic writing, especially in **computer and information science**,  
the following three elements are indispensable:

- Figures  
- Tables  
- Equations  

This section explains how to insert them in LaTeX,  
and how to refer to them using **reference numbers**.

---

## How to Insert Figures

> [!Note]
> The following explanation assumes the system configuration used in this course: **platex + dvipdfmx**.  
> Depending on the compiler and environment, supported image formats may differ.

First, prepare the image file you wish to include.  
The supported file formats are:

- `.eps`  
- `.pdf`  
- `.png`  
- `.jpg`

For **vector graphics** (e.g., plots, charts), `.pdf` is recommended.  
For **raster images** (e.g., photos, screenshots), use `.png`.

When inserting a figure in the main text, write:

```latex
\begin{figure}[htbp]
  \centering
  \includegraphics[width=0.8\linewidth]{figures/sample.png}
  \caption{Sample figure: Relationship between XXX and YYY}
\end{figure}
```

Each line has the following meaning:

- `\begin{figure}[htbp]`: Begins the figure environment.  
  `[htbp]` specifies placement preference: *here*, *top*, *bottom*, or *page*.
- `\centering`: Centers the figure.  
- `\includegraphics`: Inserts the image file.  
  `width=0.8\linewidth` scales it to 80% of the text width.  
  The `{}` part specifies the image file path.  
  For `{figures/sample.png}`, the directory structure is assumed as follows:
  ```
  Working Directory ┬ main.tex (to be compiled)
                    └ figures/ ─ sample.png
  ```
- `\caption{...}`: Adds a caption (title) below the figure.

**In research papers, figure captions are usually placed *below* the figure.**

---

## How to Insert Tables

To insert a table in the text, write:

```latex
\begin{table}[htbp]
  \centering
  \caption{List of experimental conditions}
  \begin{tabular}{lcc}
    \hline
    Condition & Temperature [℃] & Time [min] \\
    \hline
    A & 25 & 30 \\
    B & 30 & 45 \\
    C & 35 & 60 \\
    \hline
  \end{tabular}
\end{table}
```

Each line means:

- `\begin{table}[htbp]`: Starts the table environment. (`[htbp]` = placement preference)
- `\centering`: Centers the table.  
- `\caption{...}`: Adds the table title.  
- `\begin{tabular}{lcc}`: Specifies the column alignment.  
  `l` = left, `c` = center, `r` = right (here, 3 columns).  
- `\hline`: Draws a horizontal line.  
- Each row: Columns are separated by `&`, and each row ends with `\\`.

**In research papers, table captions are typically placed *above* the table.**

You can also create more complex tables using `\multirow` and `\multicolumn`.  
See [Overleaf’s Table Guide](https://www.overleaf.com/learn/latex/Tables) for details.


## Full-width Figures and Tables

In two-column documents, you may sometimes want a figure or table to span the entire page width.  
(For example: Figure 2 in `main.pdf`)

To achieve this, replace  
`\begin{table}[htbp]` or `\begin{figure}[htbp]`  
with  

`\begin{table*}[htbp]` or `\begin{figure*}[htbp]`

By adding an asterisk (`*`), the figure or table will extend across both columns.

> [!Tip]
> Some journals or conferences **prohibit full-width figures/tables**, requiring all content to fit within a single column.  
> Always check the author guidelines before submission.

---

## How to Insert Equations

You can include equations using `\begin{equation}~\end{equation}` or  
`\begin{eqnarray}~\end{eqnarray}`.

**Example 1**
```latex
\begin{equation}
E = mc^2
\end{equation}
```

The `equation` environment allows **one equation** per block.

**Example 2**
```latex
\begin{eqnarray}
a + b &=& c \\
x + y &=& z
\end{eqnarray}
```

The `eqnarray` environment allows **multiple aligned equations**.  
Like in tables, `\\` is used for line breaks, and `&` aligns the columns.

<details><summary>Tip</summary>
If you are using the `amsmath` package,  
the `align` environment (`\begin{align}~\end{align}`) produces more elegant alignment.
</details>

---

### Common Examples of Mathematical Expressions

| Category | Example | LaTeX Code | Description |
|:--|:--|:--|:--|
| **Subscripts & Superscripts** | $a_{i}$ | `a_{i}` | Subscript |
|  | $a^{n}$ | `a^{n}` | Superscript |
|  | $x_{ij}$ | `x_{ij}` | Double index |

| Category | Example | LaTeX Code | Description |
|:--|:--|:--|:--|
| **Basic Arithmetic** | $a + b = c$ | `a + b = c` | Addition |
|  | $a - b = c$ | `a - b = c` | Subtraction |
|  | $a \times b = c$ | `a \times b = c` | Multiplication |
|  | $a \div b = c$ | `a \div b = c` | Division |
|  | $\frac{a}{b} = c$ | `\frac{a}{b} = c` | Fraction |
|  | $a^2 + b^2 = c^2$ | `a^2 + b^2 = c^2` | Power |

| Category | Example | LaTeX Code | Description |
|:--|:--|:--|:--|
| **Functions** | $\sin \theta = \frac{y}{r}$ | `\sin \theta = \frac{y}{r}` | Sine |
|  | $\cos \theta = \frac{x}{r}$ | `\cos \theta = \frac{x}{r}` | Cosine |
|  | $\tan \theta = \frac{y}{x}$ | `\tan \theta = \frac{y}{x}` | Tangent |
|  | $\log_{2} 8 = 3$ | `\log_{2} 8 = 3` | Logarithm |
|  | $\max(x, y)$ | `\max(x, y)` | Maximum |
|  | $\min(x, y)$ | `\min(x, y)` | Minimum |
|  | $\sqrt{x^2 + y^2}$ | `\sqrt{x^2 + y^2}` | Square root |

| Category | Example | LaTeX Code | Description |
|:--|:--|:--|:--|
| **Calculus** | $\frac{dy}{dx} = 3x^2$ | `\frac{dy}{dx} = 3x^2` | Derivative |
|  | $\int_0^1 x^2 dx = \frac{1}{3}$ | `\int_0^1 x^2 dx = \frac{1}{3}` | Integral |
|  | $\lim_{x \to 0} \frac{\sin x}{x} = 1$ | `\lim_{x \to 0} \frac{\sin x}{x} = 1` | Limit |
|  | $\sum_{i=1}^{n} i = \frac{n(n+1)}{2}$ | `\sum_{i=1}^{n} i = \frac{n(n+1)}{2}` | Summation |
|  | $\prod_{i=1}^{n} a_i$ | `\prod_{i=1}^{n} a_i` | Product |

| Category | Example | LaTeX Code | Description |
|:--|:--|:--|:--|
| **Vectors** | $\overline{AB}$ | `\overline{AB}` | Line over (vector or segment) |
|  | $\vec{v}$ | `\vec{v}` | Arrow vector |
|  | $\vec{a} \cdot \vec{b} = \|\vec{a}\|\|\vec{b}\|\cos\theta$ | `\vec{a} \cdot \vec{b} = \|\vec{a}\|\|\vec{b}\|\cos\theta` | Inner product |
|  | $\vec{a} \times \vec{b} = \|\vec{a}\|\|\vec{b}\|\sin\theta\vec{n}$ | `\vec{a} \times \vec{b} = \|\vec{a}\|\|\vec{b}\|\sin\theta\vec{n}` | Cross product |
|  | $\|\vec{v}\| = \sqrt{x^2 + y^2 + z^2}$ | `\|\vec{v}\| = \sqrt{x^2 + y^2 + z^2}` | Norm (magnitude) |

| Category | Example | LaTeX Code | Description |
|:--|:--|:--|:--|
| **Matrices** | $\begin{bmatrix} 1 & 2 \\ 3 & 4 \end{bmatrix}$ | `\begin{bmatrix} 1 & 2 \\ 3 & 4 \end{bmatrix}` | Bracketed matrix |
|  | $\det(A) = ad - bc$ | `\det(A) = ad - bc` | Determinant |

---

### Inline Equations

For equations that appear **within a paragraph**,  
use the `$...$` syntax instead of `\begin{equation}`.  
Example: `When $a > 0$, the function increases.`

---

## Reference Numbers

Figures, tables, and equations are automatically numbered in LaTeX.  
These numbers—**reference numbers**—allow you to refer to specific items in the text.

To use reference numbers, you combine:
- `\label{}` → assign a reference name  
- `\ref{}` → refer to the assigned label

### Example: Figures and Tables

```latex
\begin{figure}[htbp]
  \centering
  \includegraphics[width=0.8\linewidth]{figures/sample.png}
  \caption{Sample figure: Relationship between XXX and YYY}
  \label{fig:sample} % ← place label here
\end{figure}

As shown in Figure~\ref{fig:sample}, ...
```

### Example: Equations

```latex
\begin{equation}
  f(x) = \lim_{x\to\infty} \int_0^x g(t)\,dt \label{eq:f-inf}
\end{equation}
As shown in Eq.~(\ref{eq:f-inf}), this represents ...
```

---

## Practice

Now, try adding figures and tables to your own `main.tex` file  
and reproduce the example `main.pdf` provided in this directory.  

Replace all “??” placeholders with appropriate reference numbers using  
`\label{}` and `\ref{}` commands.

[Next](https://github.com/kdesleep-code/Info-Literacy-Latex-Exercise/blob/main/4.%E5%8F%82%E8%80%83%E6%96%87%E7%8C%AE%EF%BD%9CReferences/README_en.md)
