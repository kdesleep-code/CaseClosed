# 5. Advanced Exercise  
Author: Kazumasa Horie  

[日本語版](README.md)

---

> [!Note]  
> This chapter is an **optional advanced exercise**.  
> The content here is **not included in the grading criteria**.

This section explains how to **set up LaTeX templates (style files)** provided by academic societies or publishers.  
Although each journal has its own format, the basic procedure is common across most publishers.

---

## How to Use Academic Style Files

- **Download the official template from the society or publisher website**  
  Most academic organizations provide “Author Kits” or “LaTeX Templates” that include `.cls` (class files) and `.bst` (bibliography style files).  
  Examples: IEEE, Springer, Elsevier, ACM, Nature, etc.  

- **Extract and place the files in the same directory as your main LaTeX source**  
  For example, if you are using `IEEEtran.cls`, place it in the same folder as `main.tex`.  
  Then modify the document preamble as follows:

  ```latex
  \documentclass[conference]{IEEEtran}  % or journal, transmag, etc.
  \usepackage[dvipdfmx]{graphicx}
  ```

- **Commonly Used LaTeX Templates (Official Sources)**

| Society / Publisher | Template Download Page |
| :------------------- | :------------------------------------------------------------ |
| IEEE | [IEEE Author Center: LaTeX Templates](https://www.ieee.org/conferences/publishing/templates.html) |
| ACM | [ACM Master Article Template](https://www.acm.org/publications/taps/word-template-workflow) |
| Springer | [Springer LaTeX Templates (LNCS)](https://www.springernature.com/gp/authors/campaigns/latex-author-support) |
| Elsevier | [Elsevier Template for LaTeX](https://www.elsevier.com/authors/tools-and-resources/latex-templates) |
| Nature Portfolio | [Nature LaTeX Template](https://www.nature.com/nature/for-authors/latex) |

> [!Note]  
> Some templates prohibit certain packages (for example, `hyperref` or redefinitions of `amsmath`).  
> Always read the **Author Guidelines** before submission and remove any packages not listed in the official template.  
> Be sure to use the `.bst` bibliography style file provided or specified by the respective journal or conference.

---

## Other Useful LaTeX Resources

### Custom Commands
[https://www.physicsread.com/latex-newcommand/](https://www.physicsread.com/latex-newcommand/)

### Tables: Multirow, Multicolumn, etc.
[https://www.overleaf.com/learn/latex/Tables](https://www.overleaf.com/learn/latex/Tables)

### Text Formatting: Bold, Italics, Underlining
[https://www.overleaf.com/learn/latex/Bold%2C_italics_and_underlining](https://www.overleaf.com/learn/latex/Bold%2C_italics_and_underlining)

### Figures: Subfigures and Parallel Layouts
[https://www.overleaf.com/learn/latex/Positioning_images_and_tables#Positioning_images](https://www.overleaf.com/learn/latex/Positioning_images_and_tables#Positioning_images)

> [!Important]  
> The [Overleaf Documentation](https://www.overleaf.com/learn) provides comprehensive explanations of a wide variety of LaTeX commands.  
> You can also use GPT or other AI assistants to learn how to perform specific types of formatting efficiently.
