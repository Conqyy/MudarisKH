# Common non-ASCII characters the LLM emits in technical summaries. pdflatex
# (T1 fontenc, no Unicode setup) hard-fails on these with "Unicode character
# not set up for use with LaTeX", so map them to LaTeX equivalents. Math symbols
# are wrapped in $...$; typographic ones map to their text form.
_UNICODE_LATEX = {
    # Greek lowercase
    "α": r"$\alpha$", "β": r"$\beta$", "γ": r"$\gamma$", "δ": r"$\delta$",
    "ε": r"$\varepsilon$", "ζ": r"$\zeta$", "η": r"$\eta$", "θ": r"$\theta$",
    "ι": r"$\iota$", "κ": r"$\kappa$", "λ": r"$\lambda$", "μ": r"$\mu$",
    "ν": r"$\nu$", "ξ": r"$\xi$", "π": r"$\pi$", "ρ": r"$\rho$",
    "σ": r"$\sigma$", "τ": r"$\tau$", "υ": r"$\upsilon$", "φ": r"$\varphi$",
    "χ": r"$\chi$", "ψ": r"$\psi$", "ω": r"$\omega$", "ϕ": r"$\phi$",
    # Greek uppercase
    "Γ": r"$\Gamma$", "Δ": r"$\Delta$", "Θ": r"$\Theta$", "Λ": r"$\Lambda$",
    "Ξ": r"$\Xi$", "Π": r"$\Pi$", "Σ": r"$\Sigma$", "Φ": r"$\Phi$",
    "Ψ": r"$\Psi$", "Ω": r"$\Omega$",
    # Relations
    "≤": r"$\leq$", "≥": r"$\geq$", "≠": r"$\neq$", "≈": r"$\approx$",
    "≡": r"$\equiv$", "∈": r"$\in$", "∉": r"$\notin$", "⊂": r"$\subset$",
    "⊆": r"$\subseteq$", "⊃": r"$\supset$", "⊇": r"$\supseteq$", "∝": r"$\propto$",
    # Arrows
    "→": r"$\rightarrow$", "←": r"$\leftarrow$", "↔": r"$\leftrightarrow$",
    "⇒": r"$\Rightarrow$", "⇐": r"$\Leftarrow$", "⇔": r"$\Leftrightarrow$",
    "↦": r"$\mapsto$",
    # Operators / misc math
    "×": r"$\times$", "÷": r"$\div$", "±": r"$\pm$", "∓": r"$\mp$",
    "·": r"$\cdot$", "∗": r"$*$", "∘": r"$\circ$", "∑": r"$\sum$",
    "∏": r"$\prod$", "∫": r"$\int$", "√": r"$\sqrt{\,}$", "∞": r"$\infty$",
    "∂": r"$\partial$", "∇": r"$\nabla$", "∧": r"$\wedge$", "∨": r"$\vee$",
    "¬": r"$\neg$", "∀": r"$\forall$", "∃": r"$\exists$", "∅": r"$\emptyset$",
    "°": r"$^{\circ}$", "′": r"$'$", "″": r"$''$",
    # Typographic
    "–": "--", "—": "---", "•": r"$\bullet$", "…": r"\ldots{}",
    "‘": "`", "’": "'", "“": "``", "”": "''", " ": " ",
}

_LATEX_SPECIALS = {
    "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$",
    "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}",
    "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
}
