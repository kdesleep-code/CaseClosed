# 4. Reference  
Author: Kazumasa Horie  

[日本語版](README.md)

---

Isaac Newton once said:

> “If I have seen further, it is by standing on the shoulders of giants.”

This famous quote beautifully captures the essence of scientific and academic progress.  
Our research is not based on pure originality, but rather built upon the accumulated knowledge of those who came before us.  
Therefore, it is essential to properly cite prior studies and situate our own work within the lineage of scholarship.

---

## What Are References?

**References** are lists of information that acknowledge the intellectual contributions of others on which your own research is built.  
They are more than mere lists of citations; they fulfill several critical functions:

**Clarifying the foundation of your argument**  
→ Shows which previous studies and discussions your work is based on.  

**Ensuring intellectual integrity and respect for prior work**  
→ Prevents misrepresentation or unintentional plagiarism.  

**Positioning your work within the academic dialogue**  
→ Clarifies how your research extends or updates existing discussions.  

---

## Why References Matter

Providing proper references is the first step toward ensuring **credibility and reproducibility** in research.  
A study is not supported solely by data or results, but also by **theoretical frameworks and prior findings** established by others.  

By listing appropriate references, you clearly show:  
> “Which research questions this study inherits, and which aspects it aims to update or challenge.”

---

## Example of a Reference

> Stephansen, J.B., Olesen, A.N., Olsen, M. et al. Neural network analysis of sleep stages enables efficient diagnosis of narcolepsy. *Nature Communications*, 9, 5229 (2018).

This reference includes all the key elements needed to uniquely identify the paper:  
**authors, title, journal, volume/issue, article number or pages, and publication year.**  

In addition, many journals assign a **DOI (Digital Object Identifier)**, a unique ID that allows direct access to the paper.  
For the example above, the DOI is:  
`10.1038/s41467-018-07229-3`  
Searching this DOI online will directly lead you to the article.

The exact **format, order, and author name style** depend on the journal’s reference guidelines.  
When using Word, formatting must often be adjusted manually, but in **LaTeX**, the **BibTeX** system automates this process using predefined templates distributed by academic societies.

---

## Using References in LaTeX

LaTeX uses a system called **BibTeX** to manage references automatically.  
With BibTeX, you can easily include, format, and update references without manual editing.  

The workflow consists of three main steps:

1. Prepare the `.bib` file (import or create)  
2. Load the `.bib` file in your LaTeX document  
3. Compile the document with BibTeX enabled  

Let’s look at each step in detail.

---

## 1. Preparing the `.bib` File

A `.bib` file is a text file containing bibliographic information, typically formatted as follows:

```bibtex
@article{Stephansen2018,
  author = {Stephansen, Jesper B. and others},
  title = {Neural network analysis of sleep stages enables efficient diagnosis of narcolepsy},
  journal = {Nature Communications},
  year = {2018},
  volume = {9},
  number = {5229},
  doi = {10.1038/s41467-018-07229-3}
}
```

### Explanation of Each Line

- `@article{Stephansen2018,}`  
  Indicates that the reference type is an article and assigns a unique key (`Stephansen2018`).  
- `author = {...}` – Author name(s)  
- `title = {...}` – Paper title  
- `journal = {...}` – Journal name  
- `year = {...}` – Year of publication  
- `volume = {...}` – Volume number  
- `number = {...}` – Issue or article number  
- `doi = {...}` – Digital Object Identifier  

Other common fields include `booktitle` (for proceedings) and `pages` (page range).  

Most journals display these items clearly on their article pages, so you can **copy and paste** them into your `.bib` file.  

**Example: Nature Communications article page**  
![example](https://github.com/user-attachments/assets/91bd3bfd-a924-48b9-bcff-0a012cee04cf)

**Example: Elsevier (ScienceDirect) “Export citation” button**  
![example](https://github.com/user-attachments/assets/14c5c4fd-ddf0-40ea-aea3-1f4474a365a4)

You can integrate multiple BibTeX entries into a single file, such as `example.bib`.  
[Example bib file](example.bib)

---

## 2. Reading the `.bib` File in LaTeX

To cite a reference in your text, use `\cite{key}`.  
At the end of your document, include the following to generate the bibliography list:

```latex
\bibliography{example}   % Reads example.bib (omit the .bib extension)
```

> [!Note]
> 1. References that exist in the `.bib` file but are **not cited** in the text will **not** appear in the list.  
> 2. The order of appearance follows the **citation order in the text**, not the order within the `.bib` file.

**Example:**

```latex
% In the main text
This study is based on \cite{Stephansen2018}.

% At the end of the document (before \end{document})
\bibliography{example}
```

---

## 3. Compiling with BibTeX

When using BibTeX, the compilation process differs slightly from the usual  
`platex main.tex → dvipdfmx main.dvi` sequence.  
The correct process is:

```bash
platex main.tex        # 1st run: generate citation index (.aux)
bibtex main            # Run BibTeX to generate .bbl
platex main.tex        # 2nd run: resolve citations
platex main.tex        # 3rd run: finalize numbering and cross-references
dvipdfmx main.dvi      # Convert to PDF
```

> **Tip:** BibTeX requires multiple passes to synchronize citations and numbering.  
> Be sure to follow the order above, or references may appear as `?`.

---

## Practice Task

Now, update your own `main.tex` file to include reference citations and reproduce the sample `main.pdf`.  
Some example `.bib` entries are provided in [example.bib].  
If any entries are missing, use the following bibliographic data:

> This paper is included in the *Proceedings of an international conference.*  
> Title: *U-Time: A Fully Convolutional Network for Time Series Segmentation Applied to Sleep Staging*  
> Author: Perslev, Mathias, et al.  
> Booktitle: *Advances in Neural Information Processing Systems*  
> Volume: 32  
> Pages: 4415–4426  
> Year: 2019  

In the current `main.tex`, parts labeled with “**??**” indicate where reference numbers should appear.  
Use `\cite{}` to assign the correct references.

---

## Submission

Submit both your `.tex` source and the compiled `.pdf` file to the **Manaba Report (Assignment #2)**.  
Intermediate files such as `.aux` or `.bbl` are not required.

**Grading criteria:**
- Author name replaced with your own  
- Proper chapter structure  
- Figures, tables, and equations are correctly displayed  
- Reference numbers are correctly linked in text  
- Bibliography list is displayed  
- Reference numbers appear properly within the text

>[!Note]
>There are some expressions in the sample (main.pdf) that are not explained in the class materials.  
>You will not be penalized if these are not reproduced.  
>However, if you research how to implement them on your own (e.g., online) and successfully reproduce them, you will receive extra credit.
