"""arXiv subject taxonomy (commonly used subset), grouped by archive."""

CATEGORY_GROUPS = {
    "Computer Science": {
        "cs.AI": "Artificial Intelligence",
        "cs.CL": "Computation and Language",
        "cs.CV": "Computer Vision and Pattern Recognition",
        "cs.CG": "Computational Geometry",
        "cs.CR": "Cryptography and Security",
        "cs.DB": "Databases",
        "cs.DC": "Distributed, Parallel, and Cluster Computing",
        "cs.DS": "Data Structures and Algorithms",
        "cs.GR": "Graphics",
        "cs.HC": "Human-Computer Interaction",
        "cs.IR": "Information Retrieval",
        "cs.LG": "Machine Learning",
        "cs.MA": "Multiagent Systems",
        "cs.NE": "Neural and Evolutionary Computing",
        "cs.RO": "Robotics",
        "cs.SE": "Software Engineering",
        "cs.SI": "Social and Information Networks",
    },
    "Statistics": {
        "stat.ML": "Machine Learning",
        "stat.AP": "Applications",
        "stat.ME": "Methodology",
        "stat.CO": "Computation",
    },
    "Electrical Engineering": {
        "eess.IV": "Image and Video Processing",
        "eess.SP": "Signal Processing",
        "eess.SY": "Systems and Control",
        "eess.AS": "Audio and Speech Processing",
    },
    "Mathematics": {
        "math.OC": "Optimization and Control",
        "math.ST": "Statistics Theory",
        "math.NA": "Numerical Analysis",
        "math.PR": "Probability",
        "math.MG": "Metric Geometry",
    },
    "Physics": {
        "physics.geo-ph": "Geophysics",
        "physics.ao-ph": "Atmospheric and Oceanic Physics",
        "physics.data-an": "Data Analysis, Statistics and Probability",
        "physics.soc-ph": "Physics and Society",
        "astro-ph.IM": "Instrumentation and Methods for Astrophysics",
        "quant-ph": "Quantum Physics",
        "cond-mat.dis-nn": "Disordered Systems and Neural Networks",
    },
    "Quantitative Biology": {
        "q-bio.QM": "Quantitative Methods",
        "q-bio.NC": "Neurons and Cognition",
        "q-bio.GN": "Genomics",
    },
    "Quantitative Finance": {
        "q-fin.CP": "Computational Finance",
        "q-fin.ST": "Statistical Finance",
    },
    "Economics": {
        "econ.EM": "Econometrics",
    },
}

CATEGORY_NAMES = {
    code: name for group in CATEGORY_GROUPS.values() for code, name in group.items()
}


def category_label(code):
    name = CATEGORY_NAMES.get(code)
    return f"{code} — {name}" if name else code
