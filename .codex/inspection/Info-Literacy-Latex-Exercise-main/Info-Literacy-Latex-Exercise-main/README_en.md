# Information Literacy Exercise (Week 2): Introduction to Academic Writing with LaTeX
Author: **Kazumasa Horie**

This repository provides the **Week 2 materials** for the *Information Literacy (Exercise)* course at the College of Informatics, University of Tsukuba.  
**LaTeX** is a typesetting system similar to Microsoft Word, widely used for writing papers, technical reports, and books.

---

## 🎯 Goal of the Exercise

**Be able to write an academic paper (including a thesis) using LaTeX.**  
In this exercise, you will learn the basics of LaTeX by compiling a PDF version of a **real research paper (summary version)** → [main.pdf](main.pdf).

---

## 🧩 Preparation

- The required reference materials are listed below:  
  - [Guide to Using COINS Computers (2017 Edition, excerpt)](./tebiki2017.pdf)
- LaTeX is already installed on the **COINS computing environment**.  
  Today, you will connect to a COINS computer via **SSH** and use LaTeX remotely.  
- Please refer to the **Week 1 materials** for connection instructions.

> [!Note]  
> You can also install LaTeX locally on your own computer.  
> However, since the installation involves many steps, we will skip that process for this class.

---

## 📘 What is LaTeX?

In short, LaTeX is a **typesetting system**—like Word—used to produce high-quality printed documents.  
It takes a **.tex file** (a “document blueprint”) and compiles it into a **.pdf file**.

For example, the following `.tex` file:

```tex
\documentclass[twocolumn,11pt]{jsarticle}
\usepackage[dvipdfmx]{graphicx}
\usepackage[dvipdfmx,bookmarks=true,colorlinks=true,linkcolor=blue,urlcolor=blue,citecolor=blue]{hyperref}
\usepackage{amsmath,amssymb}
\begin{document}
\begin{equation}
  \mathcal{L}(\theta)=\sum_{i=1}^{N}\|y_i - f_\theta(x_i)\|^2.
  \label{eq:loss}
\end{equation}
\end{document}
```

will generate a PDF containing this equation:

<img width="1210" height="245" alt="image" src="https://github.com/user-attachments/assets/8b52a2d7-5fde-425b-a645-86bd182ae3a7" />

> This is the *mean squared error* function often used in machine learning.  
> Writing such equations in Word is cumbersome and can make the document heavy.

In LaTeX, you **compile** the blueprint (the `.tex` file) into the finished product (`.pdf`).  
Unlike Word, LaTeX is *not* a “what-you-see-is-what-you-get” editor, so it may feel unfamiliar at first.  

However, compared with Word, LaTeX offers major advantages:

- Equations are easy to write and beautifully formatted  
- Global style control (page layout, numbering, references, etc.)  
- Automatic numbering and referencing of figures, tables, and equations  
- Efficient **bibliography management** through BibTeX  

LaTeX is therefore an ideal tool for writing academic papers efficiently and reproducibly.

---

## 🧭 How to Proceed

This repository contains five directories:

1. **Document Creation**  
   - Create a simple LaTeX source and compile it into a PDF.  
2. **Document Structure**  
   - Learn about sections, subsections, and paragraph formatting.  
3. **Figures, Tables, and Equations**  
   - Embed figures and tables.  
   - Write well-structured mathematical equations using LaTeX environments.  
4. **References**  
   - Manage and cite references with BibTeX.  
5. **Advanced Exercise (optional)**  
   - Tips.

Each directory includes its own README with explanations and exercises—please follow the instructions step by step.

---

### 💬 Suggested tagline for the repository description
> Learn academic writing with LaTeX — from basic compilation to producing a real, publication-style paper.
