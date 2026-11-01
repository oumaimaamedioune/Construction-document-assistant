"""Thème visuel Command Center pour l'interface Streamlit.

Ce module ne contient aucune logique métier. Il surcharge uniquement l'apparence
des composants Streamlit existants.
"""

import streamlit as st


def inject_command_center_theme() -> None:
    """Applique le thème bordeaux doux sans modifier les traitements."""
    st.markdown(
        """
        <style>
        :root {
            --cc-wine: #9f1f2d;
            --cc-wine-dark: #351b23;
            --cc-wine-soft: #f5dde1;
            --cc-lilac: #eee9f3;
            --cc-canvas: #f8f6f9;
            --cc-card: #ffffff;
            --cc-text: #262229;
            --cc-muted: #77717c;
            --cc-border: #e8e1e9;
            --cc-shadow: 0 10px 28px rgba(60, 32, 46, .07);
        }

        html, body, [data-testid="stAppViewContainer"], .stApp {
            background:
                radial-gradient(circle at 84% 4%, rgba(159,31,45,.055), transparent 23rem),
                linear-gradient(135deg, #faf9fb 0%, var(--cc-canvas) 55%, #f4eff5 100%) !important;
            color: var(--cc-text) !important;
        }

        [data-testid="stHeader"] {
            background: rgba(248,246,249,.88) !important;
            backdrop-filter: blur(14px);
            border-bottom: 1px solid rgba(232,225,233,.7);
        }

        [data-testid="stMainBlockContainer"] {
            max-width: 1480px !important;
            padding-top: 2.1rem !important;
            padding-bottom: 4rem !important;
        }

        /* Barre latérale inspirée de Command Center */
        [data-testid="stSidebar"] {
            background:
                radial-gradient(circle at 18% 5%, rgba(159,31,45,.09), transparent 15rem),
                linear-gradient(180deg, #f1edf5 0%, #ebe6f0 100%) !important;
            border-right: 1px solid #ddd5e1 !important;
            box-shadow: 8px 0 30px rgba(51,28,42,.045);
        }

        [data-testid="stSidebar"] > div:first-child {
            padding: 1.25rem .85rem 1.6rem !important;
        }

        [data-testid="stSidebar"] h1,
        [data-testid="stSidebar"] h2,
        [data-testid="stSidebar"] h3 {
            color: var(--cc-text) !important;
            letter-spacing: -.02em;
        }

        [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {
            color: #5f5963;
        }

        [data-testid="stSidebar"] [role="radiogroup"] {
            gap: .42rem !important;
        }

        [data-testid="stSidebar"] [role="radiogroup"] label {
            min-height: 2.85rem !important;
            padding: .68rem .82rem !important;
            border-radius: 13px !important;
            border: 1px solid transparent !important;
            transition: transform .16s ease, box-shadow .16s ease, background .16s ease;
        }

        [data-testid="stSidebar"] [role="radiogroup"] label:hover {
            background: rgba(255,255,255,.72) !important;
            border-color: rgba(159,31,45,.12) !important;
            transform: translateX(2px);
        }

        [data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {
            color: white !important;
            background: linear-gradient(135deg, var(--cc-wine-dark), #741c29 58%, var(--cc-wine)) !important;
            box-shadow: 0 9px 22px rgba(112,25,38,.22) !important;
            border-color: rgba(255,255,255,.12) !important;
        }

        [data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) p,
        [data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) span {
            color: white !important;
            font-weight: 650 !important;
        }

        [data-testid="stSidebar"] [role="radiogroup"] label > div:first-child {
            display: none !important;
        }

        /* Titres et bandeau principal */
        h1, h2, h3 {
            color: var(--cc-text) !important;
            letter-spacing: -.032em !important;
        }

        h1 { font-weight: 780 !important; }
        h2 { font-weight: 720 !important; }
        h3 { font-weight: 680 !important; }

        .main h1:first-of-type {
            margin-bottom: .25rem !important;
        }

        /* Cartes et conteneurs */
        [data-testid="stMetric"],
        [data-testid="stVerticalBlockBorderWrapper"] {
            background: rgba(255,255,255,.94) !important;
            border: 1px solid var(--cc-border) !important;
            border-radius: 18px !important;
            box-shadow: var(--cc-shadow) !important;
        }

        [data-testid="stMetric"] {
            padding: 1.15rem 1.2rem !important;
            min-height: 126px;
            position: relative;
            overflow: hidden;
        }

        [data-testid="stMetric"]::before {
            content: "";
            position: absolute;
            top: 0; left: 0; right: 0;
            height: 4px;
            background: linear-gradient(90deg, var(--cc-wine-dark), var(--cc-wine));
            opacity: .92;
        }

        [data-testid="stMetricLabel"] {
            color: var(--cc-muted) !important;
            font-weight: 600 !important;
        }

        [data-testid="stMetricValue"] {
            color: var(--cc-text) !important;
            font-weight: 720 !important;
            letter-spacing: -.04em !important;
        }

        /* Boutons */
        .stButton > button,
        .stDownloadButton > button,
        [data-testid="stFormSubmitButton"] > button {
            border-radius: 12px !important;
            border: 1px solid rgba(122,25,39,.2) !important;
            background: linear-gradient(135deg, #7e1b28, var(--cc-wine)) !important;
            color: #fff !important;
            font-weight: 650 !important;
            box-shadow: 0 7px 17px rgba(126,27,40,.16) !important;
            transition: transform .15s ease, box-shadow .15s ease !important;
        }

        .stButton > button:hover,
        .stDownloadButton > button:hover,
        [data-testid="stFormSubmitButton"] > button:hover {
            transform: translateY(-1px);
            box-shadow: 0 10px 22px rgba(126,27,40,.23) !important;
        }

        /* Champs, sélecteurs, uploader */
        [data-baseweb="input"] > div,
        [data-baseweb="select"] > div,
        [data-testid="stTextArea"] textarea,
        [data-testid="stFileUploaderDropzone"] {
            background: rgba(255,255,255,.9) !important;
            border: 1px solid var(--cc-border) !important;
            border-radius: 13px !important;
            box-shadow: 0 4px 13px rgba(60,32,46,.035) !important;
        }

        [data-testid="stFileUploaderDropzone"] {
            border: 1.5px dashed rgba(159,31,45,.38) !important;
            padding: 1.25rem !important;
        }

        /* Onglets */
        [data-baseweb="tab-list"] {
            gap: .45rem !important;
            background: #eee9f1 !important;
            padding: .32rem !important;
            border-radius: 13px !important;
        }

        [data-baseweb="tab"] {
            border-radius: 10px !important;
            padding: .58rem 1rem !important;
        }

        [aria-selected="true"][data-baseweb="tab"] {
            background: linear-gradient(135deg, var(--cc-wine-dark), var(--cc-wine)) !important;
            color: #fff !important;
            box-shadow: 0 5px 14px rgba(126,27,40,.18);
        }

        [data-baseweb="tab-highlight"] { display: none !important; }

        /* Tableaux */
        [data-testid="stDataFrame"],
        [data-testid="stTable"] {
            border: 1px solid var(--cc-border) !important;
            border-radius: 16px !important;
            overflow: hidden !important;
            box-shadow: 0 8px 24px rgba(60,32,46,.055) !important;
            background: white !important;
        }

        /* Messages et panneaux secondaires */
        [data-testid="stAlert"] {
            border-radius: 14px !important;
            border-left: 4px solid var(--cc-wine) !important;
            box-shadow: 0 5px 15px rgba(60,32,46,.04);
        }

        [data-testid="stExpander"] {
            border: 1px solid var(--cc-border) !important;
            border-radius: 14px !important;
            background: rgba(255,255,255,.86) !important;
            overflow: hidden;
        }

        [data-testid="stExpander"] summary:hover {
            color: var(--cc-wine) !important;
        }

        /* Badges multiselect */
        [data-baseweb="tag"] {
            background: linear-gradient(135deg, #83202d, var(--cc-wine)) !important;
            border-radius: 9px !important;
            color: white !important;
        }

        /* Progression */
        [data-testid="stProgress"] > div > div > div {
            background: linear-gradient(90deg, var(--cc-wine-dark), var(--cc-wine)) !important;
        }

        /* Petits raffinements */
        hr { border-color: var(--cc-border) !important; }
        a { color: var(--cc-wine) !important; }
        ::selection { background: #e9bfc6; color: #42131d; }

        @media (max-width: 900px) {
            [data-testid="stMainBlockContainer"] { padding: 1.25rem .8rem 3rem !important; }
            [data-testid="stMetric"] { min-height: 105px; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
