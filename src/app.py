"""Interface Streamlit locale de l'assistant d'analyse de documents BTP."""

from __future__ import annotations

import io
import json
import html
import hashlib
import importlib
import re
import shutil
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from command_center_theme import inject_command_center_theme

from evaluer_validation_nlp import evaluer_annotations
from database import (
    actualiser_document_cible,
    enregistrer_document_seul,
    initialiser_base,
    lister_analyses_nlp,
    lister_documents,
    lister_executions,
    lister_extractions,
    lister_extractions_metier,
    lister_validations_metier,
    lister_validations_extractions,
    lister_rapprochements,
    enregistrer_decision_rapprochement,
    enregistrer_validation_metier,
    enregistrer_validation_extraction,
    statistiques_tableau_de_bord,
)
from validation_nlp import (
    charger_validations,
    construire_entites_corrigees,
    formater_entites_manquantes,
    parser_entites_manquantes,
    sauvegarder_validation,
)
from analyse_nouveau_document import (
    DOSSIERS_CORPUS,
    TYPES_DOCUMENT,
    analyser_nouveau_document,
    inspecter_pdf,
    nom_securise,
    proposer_type,
)
import chatbot_btp as _module_chatbot_btp

# Streamlit réexécute ``app.py`` sans nécessairement recharger les modules déjà
# importés. Recharger explicitement le moteur empêche l'interface de continuer
# à utiliser une ancienne logique après une correction du chatbot.
_module_chatbot_btp = importlib.reload(_module_chatbot_btp)
AssistantBTP = _module_chatbot_btp.AssistantBTP
enregistrer_avis_chatbot = _module_chatbot_btp.enregistrer_avis_chatbot


RACINE_PROJET = Path(__file__).resolve().parents[1]

st.set_page_config(
    page_title="Assistant BTP | Ménara Préfa",
    page_icon="🏗️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
      .block-container {padding-top: 1.5rem; padding-bottom: 3rem;}
      [data-testid="stMetric"] {background:#ffffff; border:1px solid #e6e9ed;
        padding:1rem; border-radius:12px; box-shadow:0 2px 8px rgba(0,0,0,.04);}
      .btp-header {padding:1.2rem 1.4rem; border-radius:14px;
        background:linear-gradient(110deg,#3a3f47,#8f1f27 65%,#c9313b) !important;
        color:#ffffff !important; margin-bottom:1.2rem;}
      .btp-header h1 {margin:0; font-size:1.8rem; color:#ffffff !important;}
      .btp-header p {margin:.35rem 0 0; opacity:.95; color:#ffffff !important;}
      .status-box {padding:.75rem 1rem; border-left:4px solid #b3262e;
        background:#faf2f3; border-radius:6px; margin:.4rem 0 1rem;}
      .dash-panel {background:#fff; border:1px solid #e6e9ed; border-radius:14px;
        padding:1rem 1.1rem; box-shadow:0 3px 12px rgba(27,31,35,.045); height:100%;}
      .dash-panel-title {font-size:1rem; font-weight:700; color:#2b3035; margin-bottom:.85rem;}
      .dash-row {display:grid; grid-template-columns:minmax(120px,1fr) 2.2fr 42px;
        gap:.7rem; align-items:center; margin:.62rem 0; font-size:.86rem; color:#454b52;}
      .dash-track {height:9px; border-radius:99px; background:#f0e4e5; overflow:hidden;}
      .dash-fill {height:100%; border-radius:99px; background:linear-gradient(90deg,#7c1d24,#bd2933);}
      .dash-fill.neutral {background:linear-gradient(90deg,#555b62,#858b91);}
      .dash-count {font-weight:700; color:#7c1d24; text-align:right;}
      .activity-card {display:grid; grid-template-columns:12px 1fr auto; gap:.8rem;
        align-items:start; background:#fff; border:1px solid #e6e9ed; border-radius:12px;
        padding:.85rem 1rem; margin:.55rem 0; box-shadow:0 2px 8px rgba(0,0,0,.035);}
      .activity-dot {width:10px; height:10px; margin-top:.34rem; border-radius:50%; background:#2f9e62;
        box-shadow:0 0 0 4px #e3f5eb;}
      .activity-dot.error {background:#bd2933; box-shadow:0 0 0 4px #f9e1e3;}
      .activity-title {font-weight:700; color:#2d3339; font-size:.91rem;}
      .activity-meta {color:#71777e; font-size:.8rem; margin-top:.2rem;}
      .activity-badge {font-size:.74rem; font-weight:700; border-radius:99px; padding:.24rem .58rem;
        color:#23784a; background:#e6f5ec; white-space:nowrap;}
      .activity-badge.error {color:#9d2028; background:#f9e3e5;}
      .upload-intro {display:flex; gap:1rem; align-items:center; margin:.25rem 0 1.1rem;
        padding:1rem 1.1rem; border:1px solid #eadfe0; border-radius:14px;
        background:linear-gradient(115deg,#fff,#fbf3f4); box-shadow:0 3px 12px rgba(42,24,26,.04);}
      .upload-icon {display:flex; align-items:center; justify-content:center; flex:0 0 52px;
        width:52px; height:52px; border-radius:14px; color:white;
        background:linear-gradient(145deg,#761d24,#bd2933); box-shadow:0 7px 16px rgba(155,34,43,.2);}
      .upload-icon svg {width:27px; height:27px;}
      .upload-heading {font-size:1.05rem; font-weight:750; color:#282d32; margin-bottom:.18rem;}
      .upload-copy {font-size:.88rem; color:#697078; line-height:1.45;}
      .upload-steps {display:grid; grid-template-columns:repeat(3,1fr); gap:.65rem; margin:.2rem 0 1rem;}
      .upload-step {padding:.7rem .8rem; border-radius:10px; background:#fff;
        border:1px solid #eceff1; color:#50565d; font-size:.82rem;}
      .upload-step b {display:block; color:#8f2028; margin-bottom:.12rem;}
      .st-key-zone_import_document [data-testid="stFileUploaderDropzone"] {
        min-height:112px; border:2px dashed #d8a4a8; border-radius:14px;
        background:linear-gradient(110deg,#fff,#fcf5f6); padding:1rem 1.2rem;}
      .st-key-zone_import_document [data-testid="stFileUploaderDropzone"]:hover {
        border-color:#b3262e; background:#fff7f7;}
      .privacy-note {display:flex; align-items:center; gap:.55rem; padding:.72rem .9rem;
        color:#5a4547; background:#f7eeee; border-radius:9px; font-size:.84rem; margin-top:.65rem;}
      .privacy-note strong {color:#842028;}
      @media (max-width:760px) {.upload-steps {grid-template-columns:1fr;}}
      .small-note {color:#5d6772; font-size:.9rem;}
      /* Sidebar inspirée d'un portail professionnel, adaptée à Ménara Préfa */
      [data-testid="stSidebar"] {background:#f8f9fa; border-right:1px solid #e9ecef;}
      [data-testid="stSidebar"] > div:first-child {padding-top:1.2rem;}

      [data-testid="stSidebar"] [data-testid="stTextInput"] input {
        background:#fff url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='15' height='15' viewBox='0 0 24 24' fill='none' stroke='%23adb5bd' stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round'%3E%3Ccircle cx='11' cy='11' r='8'/%3E%3Cpath d='m21 21-4.35-4.35'/%3E%3C/svg%3E") no-repeat 14px center;
        border:1px solid #e1e4e8; border-radius:10px;
        font-size:.85rem; min-height:40px; padding-left:2.6rem; color:#343a40;
      }
      [data-testid="stSidebar"] [data-testid="stTextInput"] input:focus {
        border-color:#b3262e; box-shadow:0 0 0 3px rgba(179,38,46,.08);
      }

      [data-testid="stSidebar"] .stButton {margin:.08rem .4rem;}
[data-testid="stSidebar"] .stButton button {
  width:100% !important; min-height:42px !important; justify-content:flex-start !important;
  text-align:left !important; border:none !important; border-radius:8px !important;
  padding:.55rem .8rem !important; box-shadow:none !important;
  font-size:.92rem !important; font-weight:500 !important;
  transition:all .15s ease !important;
}
[data-testid="stSidebar"] .stButton button[kind="secondary"] {
  background:transparent !important; color:#495057 !important;
}
[data-testid="stSidebar"] .stButton button[kind="secondary"]:hover {
  background:#e9ecef !important; color:#212529 !important;
}
[data-testid="stSidebar"] .stButton button[kind="primary"] {
  background:#f8e5e6 !important; color:#8f1f27 !important; font-weight:600 !important;
  box-shadow:none !important;
}
      [data-testid="stSidebar"] .stButton button p {
        font-size:.92rem !important; line-height:1.4 !important;
        display:flex !important; align-items:center !important;
        gap:.65rem !important; margin:0 !important;
      }
      [data-testid="stSidebar"] .stButton [data-testid="stIconMaterial"] {
        color:#a3222b !important; font-size:1.18rem !important;
      }

      .side-brand {display:flex; align-items:center; gap:.72rem; padding:.35rem .5rem 1rem;}
      .side-logo {width:42px; height:42px; border-radius:12px; display:grid; place-items:center;
        background:linear-gradient(145deg,#8f1f27,#c93640); color:white; font-weight:800;
        letter-spacing:-1px; box-shadow:0 5px 14px rgba(143,31,39,.20);}
      .side-brand-title {font-size:1.08rem; font-weight:750; color:#24272b; line-height:1.18;}
      .side-brand-subtitle {font-size:.78rem; color:#70757b; margin-top:.22rem;}
      .side-section {font-size:.7rem; font-weight:700; color:#868e96; letter-spacing:.08em;
        margin:1.2rem .5rem .4rem; text-transform:uppercase;}
      [data-testid="stDataFrame"] {
        border:1px solid #e0e2e5; border-radius:11px; overflow:hidden;
        box-shadow:0 2px 8px rgba(31,35,40,.035); background:white;
      }
      [data-testid="stDataFrame"] [role="columnheader"] {
        background:#f7e9ea !important; color:#772027 !important; font-weight:700 !important;
      }
      .source-label {font-size:.82rem; color:#687078; font-weight:600; margin:.3rem 0 .38rem;}
      .source-box {background:#fff; color:#292d31; border:1px solid #dfe2e5;
        border-left:4px solid #b3262e; border-radius:9px; padding:.9rem 1rem;
        line-height:1.55; min-height:74px; max-height:240px; overflow:auto;
        white-space:pre-wrap; overflow-wrap:anywhere; user-select:text; cursor:text;
        box-shadow:0 2px 7px rgba(31,35,40,.035);}
      .source-highlight {background:#ffe59a; color:#3b2b00; border-radius:3px;
        padding:.05rem .12rem; font-weight:700;}
      .entity-highlight {background:#8f1f27; color:#fff; border-radius:3px;
        padding:.05rem .18rem; font-weight:700;}
      .btp-chart {background:#fff; border:1px solid #e3e6e9; border-radius:12px;
        padding:1rem 1.05rem; box-shadow:0 2px 8px rgba(0,0,0,.035);}
      .btp-chart-title {font-size:1rem; font-weight:750; margin-bottom:.85rem; color:#292d31;}
      .btp-bar-row {display:grid; grid-template-columns:minmax(115px,1.6fr) 3fr 42px;
        gap:.6rem; align-items:center; margin:.52rem 0;}
      .btp-bar-label {font-size:.82rem; color:#40464d; white-space:nowrap;
        overflow:hidden; text-overflow:ellipsis;}
      .btp-bar-track {height:13px; border-radius:8px; background:#f0e5e6; overflow:hidden;}
      .btp-bar-fill {height:100%; border-radius:8px;
        background:linear-gradient(90deg,#7c1d24,#b3262e);}
      .btp-bar-value {font-size:.82rem; font-weight:750; color:#7c1d24; text-align:right;}
      /* Assistant conversationnel accessible depuis toutes les pages */
      .st-key-chatbot_flottant {
        position:fixed !important; right:1.55rem !important; bottom:1.45rem !important;
        width:auto !important; z-index:99999 !important;
      }
      .st-key-chatbot_flottant [data-testid="stPopover"] button {
        width:62px !important; height:62px !important; min-height:62px !important;
        padding:0 !important; border:none !important; border-radius:50% !important;
        background:linear-gradient(145deg,#711a21,#bd2832) !important;
        color:#fff !important; font-size:0 !important;
        display:grid !important; place-items:center !important;
        box-shadow:0 10px 26px rgba(124,29,36,.38) !important;
        outline:5px solid rgba(179,38,46,.10) !important;
      }
      .st-key-chatbot_flottant [data-testid="stPopover"] button p,
      .st-key-chatbot_flottant [data-testid="stPopover"] button svg {display:none !important;}
      .st-key-chatbot_flottant [data-testid="stPopover"] button::before {
        content:""; width:38px; height:38px; display:block;
        background:center/contain no-repeat url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Cpath d='M32 11v7M28 8a4 4 0 1 0 8 0 4 4 0 1 0-8 0' fill='none' stroke='white' stroke-width='4' stroke-linecap='round'/%3E%3Crect x='12' y='18' width='40' height='34' rx='17' fill='none' stroke='white' stroke-width='4'/%3E%3Ccircle cx='25' cy='33' r='3' fill='white'/%3E%3Ccircle cx='39' cy='33' r='3' fill='white'/%3E%3Cpath d='M24 42c5 4 11 4 16 0M8 29H5m54 0h-3' fill='none' stroke='white' stroke-width='4' stroke-linecap='round'/%3E%3C/svg%3E");
      }
      .st-key-chatbot_flottant [data-testid="stPopover"] button:hover {
        transform:translateY(-2px); box-shadow:0 12px 28px rgba(124,29,36,.42) !important;
      }
      [data-testid="stPopoverBody"] {min-width:480px; max-width:530px; padding:0 !important;
        border:1px solid #e2e5e9; border-radius:17px; overflow:hidden;
        background:#f2f5f8; box-shadow:0 18px 55px rgba(31,39,48,.22);}
      .st-key-chatbot_flottant [data-testid="stPopoverBody"] > div {padding:0 !important;}
      .chat-head {display:flex; align-items:center; gap:.78rem; padding:.9rem 1rem;
        background:#fff; border-bottom:1px solid #e5e8ec; margin-bottom:.35rem;}
      .chat-avatar {width:44px; height:44px; border-radius:50%; display:grid; place-items:center;
        color:#fff; background:linear-gradient(145deg,#821e26,#bd2832);
        box-shadow:0 4px 13px rgba(125,29,37,.25); flex:0 0 auto;}
      .chat-avatar svg {width:29px; height:29px;}
      .chat-title {font-weight:780; color:#292d31; line-height:1.2; font-size:1rem;}
      .chat-subtitle {font-size:.73rem; color:#7d858e; margin-top:.1rem;}
      .chat-status {display:inline-flex; align-items:center; gap:.32rem; margin-top:.18rem;
        color:#52a66d; font-size:.69rem; font-weight:650;}
      .chat-status::before {content:""; width:7px; height:7px; border-radius:50%;
        background:#54c77a; box-shadow:0 0 0 3px rgba(84,199,122,.12);}
      /* Nouvelle conversation : bulle avec signe +, inspirée du visuel fourni. */
      .st-key-chat_btp_effacer {display:flex !important; align-items:center !important;
        justify-content:center !important; width:100% !important;}
      .st-key-chat_btp_effacer button {
        width:46px !important; height:46px !important; min-height:46px !important;
        padding:0 !important; border:1px solid #d9a8ad !important;
        border-radius:13px !important; background:#fff7f8 !important;
        display:grid !important; place-items:center !important; line-height:0 !important;
        box-shadow:0 3px 10px rgba(124,29,36,.10) !important;
      }
      .st-key-chat_btp_effacer button p,
      .st-key-chat_btp_effacer button svg {display:none !important;}
      .st-key-chat_btp_effacer button::before {
        content:""; display:block; width:34px; height:34px; margin:0;
        background:center/contain no-repeat url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Cdefs%3E%3ClinearGradient id='g' x1='8' y1='56' x2='55' y2='8' gradientUnits='userSpaceOnUse'%3E%3Cstop stop-color='%23751b23'/%3E%3Cstop offset='1' stop-color='%23c52c37'/%3E%3C/linearGradient%3E%3C/defs%3E%3Cpath d='M10 30c0-12 9-21 22-21 7 0 13 2 17 7-5 3-8 8-8 14 0 5 2 9 6 12-4 5-10 8-17 8h-5L14 57l3-12c-5-4-7-9-7-15Z' fill='none' stroke='url(%23g)' stroke-width='5' stroke-linecap='round' stroke-linejoin='round'/%3E%3Ccircle cx='47' cy='23' r='12' fill='url(%23g)'/%3E%3Cpath d='M47 17v12M41 23h12' stroke='white' stroke-width='3.5' stroke-linecap='round'/%3E%3Cpath d='M22 29h12M22 36h16' stroke='url(%23g)' stroke-width='4' stroke-linecap='round'/%3E%3C/svg%3E");
      }
      .st-key-chat_btp_effacer button:hover {
        transform:translateY(-1px); background:#f9e6e8 !important;
        border-color:#b3262e !important; box-shadow:0 5px 14px rgba(124,29,36,.18) !important;
      }
      .st-key-chatbot_flottant [data-testid="stChatMessage"] {margin:.45rem .8rem;
        padding:.68rem .72rem; border-radius:14px 14px 14px 4px; border:1px solid #e7eaee;
        background:#fff; box-shadow:0 2px 7px rgba(31,39,48,.04);}
      .st-key-chatbot_flottant [data-testid="stChatMessage"]:has(.assistant-message-marker) {
        background:linear-gradient(135deg,#fff7f8 0%,#f5dfe2 52%,#eabfc4 100%) !important;
        border:1px solid #d99ca3 !important; border-left:5px solid #a6232c !important;
        box-shadow:0 6px 17px rgba(124,29,36,.14) !important;
        color:#3d2024 !important;
      }
      .st-key-chatbot_flottant [data-testid="stChatMessage"]:has(.user-message-marker) {
        background:linear-gradient(135deg,#fff 0%,#f5f6f8 100%) !important;
        border:1px solid #dce1e6 !important; border-right:4px solid #7d858d !important;
        border-radius:14px 14px 4px 14px;
      }
      .assistant-message-marker,.user-message-marker {display:none !important;}
      .st-key-chatbot_flottant [data-testid="stChatMessage"] p {font-size:.88rem; line-height:1.48;}
      .st-key-chatbot_flottant [data-testid="stChatMessageAvatarUser"] {
        background:#f6e2e4 !important; color:#9b222b !important;}
      .st-key-chatbot_flottant [data-testid="stChatMessageAvatarAssistant"] {
        background:#98232c !important; color:#fff !important;}
      .st-key-chatbot_flottant [data-testid="stForm"] {margin:.5rem .8rem .85rem;
        padding:.5rem .58rem .58rem; border:1px solid #d9a8ad; border-radius:14px; background:#fff;
        position:sticky; bottom:.15rem; z-index:8; box-shadow:0 -6px 18px rgba(55,32,35,.08);}
      .st-key-chatbot_flottant [data-testid="stForm"] p {margin-bottom:.18rem !important;}
      .st-key-chatbot_flottant [data-testid="stForm"] [data-testid="stTextInput"] {margin-bottom:0 !important;}
      .st-key-chatbot_flottant [data-testid="stFormSubmitButton"] button {
        min-height:40px !important; height:40px !important; margin-top:0 !important;
        white-space:nowrap !important; padding:.35rem .55rem !important;}
      .st-key-chatbot_flottant [data-testid="stExpander"] {border:1px solid #d8aeb3 !important;
        border-radius:11px !important; overflow:hidden;
        background:linear-gradient(135deg,#fffafa,#f8e9eb) !important;
        box-shadow:0 3px 10px rgba(124,29,36,.07) !important;}
      .st-key-chatbot_flottant [data-testid="stExpander"] summary {
        color:#762029 !important; font-weight:720 !important;
        background:linear-gradient(90deg,#f9e7e9,#f1d3d7) !important;}
      .st-key-chatbot_flottant [data-testid="stExpander"] summary:hover {
        color:#fff !important; background:linear-gradient(90deg,#852029,#b72933) !important;}
      .chat-row {display:flex; align-items:flex-end; gap:.48rem; margin:.62rem .75rem;}
      .chat-row-user {justify-content:flex-end;}
      .chat-bot-mini {width:29px; height:29px; flex:0 0 29px; border-radius:50%;
        display:grid; place-items:center; background:linear-gradient(145deg,#7a1b23,#bd2933);
        box-shadow:0 3px 9px rgba(124,29,36,.24);}
      .chat-bot-mini svg {width:18px; height:18px;}
      .chat-bubble {max-width:82%; padding:.72rem .84rem; font-size:.88rem;
        line-height:1.5; overflow-wrap:anywhere;}
      .chat-bubble-assistant {color:#3b2528;
        background:linear-gradient(135deg,#fff8f9 0%,#f3d5d9 62%,#e8b8be 100%);
        border:1px solid #d99ba2; border-radius:15px 15px 15px 4px;
        box-shadow:0 5px 14px rgba(124,29,36,.13);}
      .chat-bubble-user {color:#fff;
        background:linear-gradient(135deg,#7b1b23 0%,#a9232d 60%,#c9313b 100%);
        border:1px solid #8b2028; border-radius:15px 15px 4px 15px;
        box-shadow:0 5px 14px rgba(124,29,36,.22);}
      .chat-bubble strong {font-weight:780;}
      .chat-bullet {display:block; position:relative; margin:.42rem 0; padding-left:1rem;
        width:100%; box-sizing:border-box;}
      .chat-bullet::before {content:""; position:absolute; left:0; top:.5rem;
        width:6px; height:6px; border-radius:50%; background:#a9232d;}
      .chat-bubble-user .chat-bullet::before {background:#fff;}
      .chat-sources-wrap {margin:.2rem .75rem .68rem 2.7rem;}
      .chat-source {font-size:.78rem; color:#626a72; border-left:3px solid #b3262e;
        background:#faf5f5; padding:.45rem .6rem; border-radius:5px; margin:.35rem 0;}
      .chat-proof-badge {display:inline-flex; align-items:center; gap:.35rem; margin:.05rem 0 .35rem 2.7rem;
        padding:.28rem .55rem; border-radius:999px; background:#f7e7e9; color:#852029;
        font-size:.72rem; font-weight:700; border:1px solid #e7c1c5;}
      .chat-proof-card {padding:.55rem .65rem; margin:.38rem 0; border-radius:9px;
        background:#fff; border:1px solid #ead7d9; border-left:4px solid #a9232d;}
      .chat-proof-title {font-size:.79rem; font-weight:750; color:#4b292d; overflow-wrap:anywhere;}
      .chat-proof-text {font-size:.74rem; line-height:1.42; color:#62666b; margin-top:.28rem;
        display:-webkit-box; -webkit-line-clamp:3; -webkit-box-orient:vertical; overflow:hidden;}
      .chat-feedback-note {font-size:.7rem; color:#737980; margin:.08rem 2.8rem .2rem;}
      .st-key-chatbot_flottant [class*="st-key-chat_feedback_"] button {
        min-height:28px !important; height:28px !important; width:32px !important;
        padding:0 !important; border-radius:50% !important; font-size:.82rem !important;
        color:#792028 !important; border:1px solid #dfb8bc !important;
        background:#fff9f9 !important; box-shadow:none !important;}
      .st-key-chatbot_flottant [class*="st-key-chat_feedback_"] button:hover {
        background:#f2dadd !important; border-color:#ad2730 !important;}
      @media (max-width:700px) {
        [data-testid="stPopoverBody"] {min-width:92vw; max-width:92vw;}
        .st-key-chatbot_flottant {right:.85rem !important; bottom:.85rem !important;}
      }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data(ttl=300)
def charger_stats():
    return statistiques_tableau_de_bord()


@st.cache_data(ttl=300)
def charger_documents():
    return lister_documents()


@st.cache_data(ttl=300)
def charger_extractions():
    return lister_extractions()


@st.cache_data(ttl=300)
def charger_executions():
    return lister_executions()


@st.cache_data(ttl=300)
def charger_analyses_nlp():
    return lister_analyses_nlp()


@st.cache_data(ttl=300)
def charger_extractions_metier():
    return lister_extractions_metier()


def _empreinte_moteur_chatbot() -> str:
    """Retourne une version qui change dès que le moteur du chatbot change.

    Cette empreinte évite qu'une ancienne instance mise en cache continue à
    répondre avec des règles qui viennent d'être corrigées.
    """
    moteur = Path(__file__).with_name("chatbot_btp.py")
    try:
        return hashlib.sha256(moteur.read_bytes()).hexdigest()[:12]
    except OSError:
        # Le repli conserve une valeur stable si le fichier est momentanément
        # inaccessible, sans empêcher le démarrage de l'application.
        return "chatbot-indisponible"


VERSION_CHATBOT = _empreinte_moteur_chatbot()


@st.cache_resource
def charger_assistant_btp(version: str):
    """Charge exactement la version demandée du moteur documentaire.

    La version est l'empreinte des fichiers du moteur : le cache est donc
    renouvelé automatiquement après une correction, tout en gardant des
    réponses rapides entre deux questions.
    """
    del version
    module = importlib.reload(importlib.import_module("chatbot_btp"))
    return module.AssistantBTP()


@st.cache_data(ttl=120)
def charger_rapprochements():
    return lister_rapprochements()


def aplatir_extractions(extractions: list[dict]) -> pd.DataFrame:
    lignes = []
    for element in extractions:
        donnees = element.get("donnees", {})
        ligne = {
            "id": element["id"],
            "document": element["nom_fichier"],
            "type": element["type_document"],
            "page": element["page"],
            "categorie": element["categorie"],
            "libelle": element["libelle"],
            "section": element.get("section"),
            "statut": element["statut_validation"],
            "texte_source": element.get("texte_source") or donnees.get("texte_source"),
        }
        for cle, valeur in donnees.items():
            if cle not in {"texte_source", "section"}:
                ligne[cle] = ", ".join(map(str, valeur)) if isinstance(valeur, list) else valeur
        lignes.append(ligne)
    return pd.DataFrame(lignes)


def generer_excel(dataframe: pd.DataFrame) -> bytes:
    sortie = io.BytesIO()
    with pd.ExcelWriter(sortie, engine="openpyxl") as writer:
        dataframe.to_excel(writer, index=False, sheet_name="Toutes_extractions")
        if "type" in dataframe.columns:
            for type_document in ("CCTP", "DQE"):
                sous_ensemble = dataframe[dataframe["type"] == type_document]
                if not sous_ensemble.empty:
                    sous_ensemble.to_excel(writer, index=False, sheet_name=type_document)
    return sortie.getvalue()


def entete():
    st.markdown(
        """
        <div class="btp-header">
          <h1>Assistant intelligent d'analyse de documents BTP</h1>
          <p>Extraction vérifiable, contrôle métier et traçabilité locale</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def afficher_texte_source(titre: str, texte, recherche: str = "") -> None:
    """Affiche une preuve lisible, sélectionnable et sans champ désactivé."""
    texte_brut = str(texte or "Aucun texte source disponible.")
    terme = str(recherche or "").strip()
    if terme:
        morceaux = re.split(f"({re.escape(terme)})", texte_brut, flags=re.IGNORECASE)
        contenu = "".join(
            f'<span class="source-highlight">{html.escape(morceau)}</span>'
            if morceau.casefold() == terme.casefold()
            else html.escape(morceau)
            for morceau in morceaux
        )
    else:
        contenu = html.escape(texte_brut)
    st.markdown(
        f'<div class="source-label">{html.escape(titre)}</div>'
        f'<div class="source-box">{contenu}</div>',
        unsafe_allow_html=True,
    )


def afficher_texte_source_entites(titre: str, texte, valeurs: list[str]) -> None:
    """Surligne en bordeaux les entités réellement présentes dans la preuve."""
    texte_brut = str(texte or "Aucun texte source disponible.")
    termes = sorted(
        {str(valeur).strip() for valeur in valeurs if str(valeur).strip()},
        key=len,
        reverse=True,
    )
    if termes:
        motif = "(" + "|".join(re.escape(terme) for terme in termes) + ")"
        morceaux = re.split(motif, texte_brut, flags=re.IGNORECASE)
        termes_normalises = {terme.casefold() for terme in termes}
        contenu = "".join(
            f'<span class="entity-highlight">{html.escape(morceau)}</span>'
            if morceau.casefold() in termes_normalises
            else html.escape(morceau)
            for morceau in morceaux
        )
    else:
        contenu = html.escape(texte_brut)
    st.markdown(
        f'<div class="source-label">{html.escape(titre)}</div>'
        f'<div class="source-box">{contenu}</div>',
        unsafe_allow_html=True,
    )


def afficher_graphique_barres(titre: str, donnees: pd.DataFrame, etiquette: str, valeur: str) -> None:
    """Affiche un graphique horizontal natif, sans dépendance graphique externe."""
    maximum = max(float(donnees[valeur].max()), 1.0) if not donnees.empty else 1.0
    lignes = []
    for _, ligne in donnees.sort_values(valeur, ascending=False).iterrows():
        nombre = float(ligne[valeur])
        largeur = max(3.0, 100 * nombre / maximum)
        nombre_affiche = int(nombre) if nombre.is_integer() else round(nombre, 1)
        lignes.append(
            '<div class="btp-bar-row">'
            f'<div class="btp-bar-label" title="{html.escape(str(ligne[etiquette]))}">'
            f'{html.escape(str(ligne[etiquette]))}</div>'
            f'<div class="btp-bar-track"><div class="btp-bar-fill" style="width:{largeur:.1f}%"></div></div>'
            f'<div class="btp-bar-value">{nombre_affiche}</div>'
            '</div>'
        )
    st.markdown(
        f'<div class="btp-chart"><div class="btp-chart-title">{html.escape(titre)}</div>'
        + "".join(lignes) + "</div>",
        unsafe_allow_html=True,
    )


def formater_source_validation(annotation: dict) -> str:
    """Présente la preuve selon la structure du document sans changer sa valeur."""
    texte = str(annotation.get("texte_source") or "").strip()
    donnees = annotation.get("donnees_source") or {}
    if annotation.get("type_document") != "DQE" or not donnees:
        return texte.lstrip("•▪◦� \t") or "Aucun texte source disponible."

    def nombre_fr(valeur, monnaie: bool = False) -> str:
        if valeur is None or valeur == "":
            return ""
        if isinstance(valeur, (int, float)):
            resultat = f"{float(valeur):,.2f}"
            resultat = resultat.replace(",", " ").replace(".", ",")
        else:
            resultat = str(valeur)
        return f"{resultat} €" if monnaie else resultat

    champs = [
        ("Numéro de poste", donnees.get("numero_poste")),
        ("Désignation", annotation.get("libelle")),
        ("Unité", donnees.get("unite")),
        ("Quantité", nombre_fr(donnees.get("quantite"))),
        ("Prix unitaire", nombre_fr(donnees.get("prix_unitaire"), monnaie=True)),
        ("Prix total", nombre_fr(donnees.get("prix_total"), monnaie=True)),
    ]
    lignes = [f"{libelle} : {valeur}" for libelle, valeur in champs if valeur not in (None, "")]
    return "\n".join(lignes) or texte or "Aucun texte source disponible."


def page_tableau_de_bord():
    entete()
    stats = charger_stats()
    statuts = stats.get("par_statut", {})
    documents = charger_documents()
    types_documents: dict[str, int] = {}
    noms_types = {
        "CCTP": "CCTP", "DQE": "DQE / devis", "CONTRAT": "Contrats",
        "GUIDE_METIER": "Guides métier", "REPORTAGE_TECHNIQUE": "Reportages techniques",
    }
    for document in documents:
        code = str(document.get("categorie_metier") or document.get("type_document") or "AUTRE")
        libelle = noms_types.get(code, code.replace("_", " ").title())
        types_documents[libelle] = types_documents.get(libelle, 0) + 1

    a_controler = statuts.get("incomplet", 0) + statuts.get("a_verifier", 0)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Documents analysés", stats["documents"])
    col2.metric("Informations extraites", stats["extractions"])
    col3.metric("Résultats validés", statuts.get("valide", 0))
    col4.metric("Vérifications restantes", a_controler)

    st.subheader("Synthèse métier")
    gauche, droite = st.columns(2)
    with gauche:
        maximum = max(types_documents.values(), default=1)
        lignes = []
        for libelle, nombre in sorted(types_documents.items(), key=lambda item: item[1], reverse=True):
            largeur = max(5, round(nombre * 100 / maximum))
            lignes.append(
                f'<div class="dash-row"><span>{html.escape(libelle)}</span>'
                f'<div class="dash-track"><div class="dash-fill" style="width:{largeur}%"></div></div>'
                f'<span class="dash-count">{nombre}</span></div>'
            )
        st.markdown(
            '<div class="dash-panel"><div class="dash-panel-title">Répartition documentaire</div>'
            + "".join(lignes) + "</div>", unsafe_allow_html=True,
        )
    with droite:
        noms_statuts = {
            "a_verifier": "À vérifier", "incomplet": "Incomplet",
            "valide": "Validé", "extrait": "Extrait automatiquement",
        }
        maximum = max(statuts.values(), default=1)
        lignes = []
        for code, nombre in sorted(statuts.items(), key=lambda item: item[1], reverse=True):
            largeur = max(5, round(nombre * 100 / maximum))
            lignes.append(
                f'<div class="dash-row"><span>{noms_statuts.get(code, code.replace("_", " ").title())}</span>'
                f'<div class="dash-track"><div class="dash-fill neutral" style="width:{largeur}%"></div></div>'
                f'<span class="dash-count">{nombre}</span></div>'
            )
        st.markdown(
            '<div class="dash-panel"><div class="dash-panel-title">État des contrôles</div>'
            + "".join(lignes) + "</div>", unsafe_allow_html=True,
        )

    st.subheader("Activité récente")
    executions = charger_executions()
    if executions:
        cartes = []
        for execution in executions[:5]:
            succes = execution.get("statut") == "succes"
            debut = pd.to_datetime(execution.get("date_debut"), errors="coerce")
            fin = pd.to_datetime(execution.get("date_fin"), errors="coerce")
            date_lisible = debut.strftime("%d/%m/%Y à %H:%M") if not pd.isna(debut) else "Date inconnue"
            duree = ""
            if not pd.isna(debut) and not pd.isna(fin):
                secondes = max(0, int((fin - debut).total_seconds()))
                duree = f" · durée {secondes} s"
            nb_documents = int(execution.get("nb_documents") or 0)
            nb_extractions = int(execution.get("nb_extractions") or 0)
            classe = "" if succes else " error"
            cartes.append(
                f'<div class="activity-card"><span class="activity-dot{classe}"></span><div>'
                f'<div class="activity-title">{"Analyse terminée" if succes else "Analyse interrompue"}</div>'
                f'<div class="activity-meta">{date_lisible} · {nb_documents} document(s) · '
                f'{nb_extractions} information(s){duree}</div></div>'
                f'<span class="activity-badge{classe}">{"Réussie" if succes else "Erreur"}</span></div>'
            )
        st.markdown("".join(cartes), unsafe_allow_html=True)

        if len(executions) > 5:
            with st.expander("Voir l’historique technique"):
                df = pd.DataFrame(executions)
                colonnes = [c for c in ["date_debut", "statut", "nb_documents", "nb_extractions"] if c in df]
                df = df[colonnes].rename(columns={
                    "date_debut": "Date", "statut": "Statut",
                    "nb_documents": "Documents", "nb_extractions": "Informations",
                })
                st.dataframe(df, width="stretch", hide_index=True)
    else:
        st.info("Aucune exécution enregistrée.")


def page_documents():
    entete()
    st.subheader("Documents du corpus")
    documents = charger_documents()
    df = pd.DataFrame(documents)
    if df.empty:
        st.warning("Aucun document enregistré.")
        return

    categories_disponibles = sorted(df["categorie_metier"].dropna().unique())
    filtre_categorie = st.multiselect(
        "Catégorie métier", categories_disponibles, default=categories_disponibles
    )
    libelles_statuts = {
        "importe": "Importé — analyse à lancer",
        "traite": "Traité",
        "sans_extraction": "Analysé — aucun résultat",
        "erreur": "Erreur de traitement",
    }
    statuts_disponibles = sorted(df["statut"].dropna().unique())
    filtre_statut = st.multiselect(
        "État du traitement", statuts_disponibles, default=statuts_disponibles,
        format_func=lambda valeur: libelles_statuts.get(valeur, valeur),
    )
    filtre = df[
        df["categorie_metier"].isin(filtre_categorie) & df["statut"].isin(filtre_statut)
    ]
    colonnes = [
        "id", "nom_fichier", "categorie_metier", "nombre_pages", "nombre_extractions",
        "statut", "taille_octets", "date_derniere_analyse",
    ]
    affichage = filtre[colonnes].copy()
    affichage["statut"] = affichage["statut"].map(libelles_statuts).fillna(affichage["statut"])
    affichage["date_derniere_analyse"] = affichage["date_derniere_analyse"].fillna("Non analysé")
    affichage = affichage.rename(columns={
        "id": "ID",
        "nom_fichier": "Document",
        "categorie_metier": "Catégorie métier",
        "nombre_pages": "Pages",
        "nombre_extractions": "Résultats",
        "statut": "État du traitement",
        "taille_octets": "Taille (octets)",
        "date_derniere_analyse": "Dernière analyse",
    })
    st.dataframe(affichage, width="stretch", hide_index=True)

    importes = filtre[filtre["statut"] == "importe"]
    if not importes.empty:
        st.info(
            f"{len(importes)} document(s) sont conservés et attendent une analyse métier."
        )

    sans_extraction = filtre[filtre["statut"] == "sans_extraction"]
    if not sans_extraction.empty:
        st.warning(
            f"{len(sans_extraction)} document(s) sont enregistrés sans extraction. "
            "Ils restent visibles afin de ne pas masquer les limites du système."
        )


def page_extractions():
    entete()
    st.subheader("Résultats extraits et traçabilité")
    extractions = charger_extractions()
    df = aplatir_extractions(extractions)
    if df.empty:
        st.warning("Aucune extraction enregistrée.")
        return

    ligne1, ligne2, ligne3 = st.columns(3)
    types = sorted(df["type"].dropna().unique())
    statuts = sorted(df["statut"].dropna().unique())
    documents = sorted(df["document"].dropna().unique())
    filtre_type = ligne1.multiselect("Type", types, default=types)
    filtre_statut = ligne2.multiselect("Statut", statuts, default=statuts)
    filtre_document = ligne3.multiselect("Document", documents, default=documents)
    recherche = st.text_input("Rechercher dans le libellé ou le texte source", placeholder="Ex. béton, NF EN 206, poteaux...")

    filtre = df[
        df["type"].isin(filtre_type)
        & df["statut"].isin(filtre_statut)
        & df["document"].isin(filtre_document)
    ].copy()
    if recherche:
        masque = (
            filtre["libelle"].fillna("").str.contains(recherche, case=False, regex=False)
            | filtre["texte_source"].fillna("").str.contains(recherche, case=False, regex=False)
        )
        filtre = filtre[masque]

    st.caption(f"{len(filtre)} résultat(s) affiché(s)")
    principales = [
        c for c in ["document", "type", "page", "categorie", "libelle", "statut", "unite", "quantite", "prix_unitaire", "prix_total"]
        if c in filtre.columns
    ]
    st.dataframe(filtre[principales], width="stretch", hide_index=True, height=430)

    if not filtre.empty:
        ids = filtre["id"].tolist()
        lignes_par_id = {ligne["id"]: ligne for _, ligne in filtre.iterrows()}

        def libelle_preuve(identifiant):
            ligne = lignes_par_id[identifiant]
            libelle = str(ligne.get("libelle") or "Sans libellé")
            document = str(ligne.get("document") or "Document inconnu")
            if ligne.get("type") == "DQE":
                poste = ligne.get("numero_poste")
                repere = f"poste {poste}" if pd.notna(poste) and poste != "" else f"page {ligne.get('page')}"
            else:
                repere = f"page {ligne.get('page')}"
            return f"{ligne.get('type')} — {repere} — {libelle} — {document}"

        extraction_id = st.selectbox(
            "Vérifier une extraction dans le document source",
            ids,
            format_func=libelle_preuve,
        )
        detail = filtre[filtre["id"] == extraction_id].iloc[0]
        c1, c2 = st.columns([1, 2])
        with c1:
            st.write(f"**Document :** {detail['document']}")
            st.write(f"**Page :** {detail['page']}")
            st.write(f"**Catégorie :** {detail['categorie']}")
            st.write(f"**Statut :** {detail['statut']}")
        with c2:
            terme = str(recherche or "").strip()
            libelle_detail = str(detail.get("libelle") or "")
            texte_detail = str(detail.get("texte_source") or "")
            if terme and terme.casefold() in libelle_detail.casefold():
                afficher_texte_source(
                    "Libellé de l'extraction", libelle_detail, recherche=terme
                )
            afficher_texte_source(
                "Texte source", texte_detail, recherche=terme
            )

    st.subheader("Exporter la sélection")
    export = filtre.copy()
    e1, e2, e3 = st.columns(3)
    e1.download_button(
        "Télécharger CSV", export.to_csv(index=False).encode("utf-8-sig"),
        file_name="extractions_btp.csv", mime="text/csv",
    )
    e2.download_button(
        "Télécharger JSON", export.to_json(orient="records", force_ascii=False, indent=2).encode("utf-8"),
        file_name="extractions_btp.json", mime="application/json",
    )
    e3.download_button(
        "Télécharger Excel", generer_excel(export),
        file_name="extractions_btp.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def page_entites_nlp():
    entete()
    st.subheader("Informations techniques reconnues par le NLP")
    analyses = charger_analyses_nlp()
    if not analyses:
        st.warning("Aucune analyse NLP enregistrée. Lancez python src\\run_pipeline.py")
        return

    noms_categories = {
        "materiaux": "Matériaux", "ouvrages_equipements": "Ouvrages / équipements",
        "normes": "Normes", "classes_beton": "Classes de béton",
        "resistances": "Résistances", "dosages": "Dosages",
        "diametres": "Diamètres", "epaisseurs": "Épaisseurs",
        "dimensions": "Dimensions", "mesures": "Mesures",
        "proprietes": "Propriétés", "type_ciment": "Type de ciment",
    }

    def afficher_valeur(valeur):
        if isinstance(valeur, dict) and "valeur" in valeur:
            nombre = valeur["valeur"]
            nombre = int(nombre) if isinstance(nombre, float) and nombre.is_integer() else nombre
            return f"{nombre} {valeur.get('unite', '')}".strip()
        return str(valeur)

    lignes = []
    for analyse in analyses:
        for categorie, valeurs in analyse.get("entites", {}).items():
            for valeur in valeurs:
                lignes.append({
                    "extraction_id": analyse["extraction_id"],
                    "document": analyse["nom_fichier"],
                    "type": analyse["type_document"],
                    "page": analyse["page"],
                    "categorie_code": categorie,
                    "categorie": noms_categories.get(categorie, categorie),
                    "valeur": afficher_valeur(valeur),
                    "libelle": analyse["libelle"],
                    "texte_source": analyse["texte_source"],
                    "version_nlp": analyse["version_nlp"],
                })
    df = pd.DataFrame(lignes)
    if df.empty:
        st.info("Les analyses existent, mais aucune entité technique n'a été reconnue.")
        return

    f1, f2, f3 = st.columns(3)
    types = sorted(df["type"].unique())
    categories = sorted(df["categorie"].unique())
    documents = sorted(df["document"].unique())
    filtre_types = f1.multiselect("Type de document", types, default=types)
    filtre_categories = f2.multiselect("Catégorie technique", categories, default=categories)
    filtre_documents = f3.multiselect("Document", documents, default=documents)
    recherche = st.text_input(
        "Rechercher une information",
        placeholder="Ex. béton, CPJ, NF EN 206, 20 cm...",
        key="recherche_entites_nlp",
    )

    filtre = df[
        df["type"].isin(filtre_types)
        & df["categorie"].isin(filtre_categories)
        & df["document"].isin(filtre_documents)
    ].copy()
    if recherche:
        masque = (
            filtre["valeur"].str.contains(recherche, case=False, regex=False)
            | filtre["libelle"].fillna("").str.contains(recherche, case=False, regex=False)
            | filtre["texte_source"].fillna("").str.contains(recherche, case=False, regex=False)
        )
        filtre = filtre[masque]

    onglet_synthese, onglet_exploration = st.tabs(
        ["Synthèse NLP", "Explorer et vérifier"]
    )

    with onglet_synthese:
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Passages analysés", filtre["extraction_id"].nunique())
        m2.metric("Entités reconnues", len(filtre))
        m3.metric("Catégories", filtre["categorie"].nunique())
        m4.metric("Documents concernés", filtre["document"].nunique())

        if filtre.empty:
            st.warning("Aucune entité ne correspond aux filtres sélectionnés.")
        else:
            repartition = (
                filtre.groupby("categorie", as_index=False)
                .size()
                .rename(columns={"size": "Nombre"})
                .sort_values("Nombre", ascending=True)
            )
            frequentes = (
                filtre.groupby("valeur", as_index=False)
                .size()
                .rename(columns={"size": "Occurrences"})
                .sort_values("Occurrences", ascending=False)
                .head(10)
                .sort_values("Occurrences", ascending=True)
            )
            gauche, droite = st.columns(2)
            with gauche:
                afficher_graphique_barres(
                    "Répartition par catégorie", repartition, "categorie", "Nombre"
                )
            with droite:
                afficher_graphique_barres(
                    "Valeurs les plus fréquentes", frequentes, "valeur", "Occurrences"
                )

    with onglet_exploration:
        st.caption(f"{len(filtre)} entité(s) affichée(s)")
        colonnes = ["document", "type", "page", "categorie", "valeur", "libelle"]
        st.dataframe(
            filtre[colonnes], hide_index=True, width="stretch", height=420
        )

        if not filtre.empty:
            preuves = filtre.drop_duplicates("extraction_id")
            extraction_id = st.selectbox(
                "Vérifier les entités dans le document source",
                preuves["extraction_id"].tolist(),
                format_func=lambda identifiant: next(
                    f"{ligne.type} — page {ligne.page} — {ligne.libelle} — "
                    f"{len(df[df['extraction_id'] == identifiant])} entité(s)"
                    for ligne in preuves.itertuples() if ligne.extraction_id == identifiant
                ),
            )
            detail = preuves[preuves["extraction_id"] == extraction_id].iloc[0]
            entites_detail = df[df["extraction_id"] == extraction_id][
                ["categorie", "valeur"]
            ].drop_duplicates()
            st.markdown("### Informations reconnues dans ce passage")
            st.dataframe(entites_detail, hide_index=True, width="stretch")
            afficher_texte_source_entites(
                "Preuve dans le texte source",
                detail["texte_source"],
                entites_detail["valeur"].tolist(),
            )

        st.download_button(
            "Télécharger les entités filtrées (CSV)",
            filtre[colonnes].to_csv(index=False).encode("utf-8-sig"),
            file_name="entites_nlp_btp.csv", mime="text/csv",
        )


def page_documents_metier():
    entete()
    st.subheader("Documents métier : clauses, règles et retours d'expérience")
    extractions = charger_extractions_metier()
    if not extractions:
        st.warning("Aucun résultat métier enregistré. Lancez python src\\run_pipeline.py")
        return

    noms_types = {
        "CONTRAT": "Contrat de travaux",
        "GUIDE_METIER": "Guide métier",
        "REPORTAGE_TECHNIQUE": "Reportage technique",
        "RAPPORT_CHANTIER": "Rapport de chantier",
    }
    noms_categories = {
        "identification": "Identification", "parties": "Parties et représentants",
        "objet_travaux": "Objet et travaux", "prix": "Prix", "modifications": "Modifications",
        "suspension": "Suspension", "sous_traitance_securite": "Sous-traitance et sécurité",
        "delais_penalites": "Délais et pénalités", "paiement": "Paiement", "garantie": "Garantie",
        "resiliation": "Résiliation", "loi_differends": "Loi et différends",
        "clause_generale": "Clause générale", "document_suivi": "Document de suivi",
        "obligation": "Obligation", "recommandation": "Recommandation",
        "risque_preuve": "Risque, preuve et réclamation",
        "cas_chantier_technique": "Cas de chantier technique",
    }
    noms_statuts = {
        "extrait": "Extrait",
        "a_verifier": "À vérifier",
        "valide": "Validé",
        "corrige": "Corrigé",
    }
    lignes = []
    for element in extractions:
        donnees = element.get("donnees", {})
        lignes.append({
            "id": element["id"], "document": element["nom_fichier"],
            "chemin": element["chemin_relatif"], "type_code": element["type_document"],
            "type": noms_types.get(element["type_document"], element["type_document"]),
            "page": element["page"], "categorie_code": element["categorie"],
            "categorie": noms_categories.get(element["categorie"], element["categorie"].replace("_", " ").title()),
            "information": element["libelle"], "texte_source": element.get("texte_source") or "",
            "qualite": element["qualite_texte"], "statut": element["statut_validation"],
            "statut_affiche": noms_statuts.get(element["statut_validation"], element["statut_validation"]),
            "renseigne": donnees.get("renseigne"), "valeur": donnees.get("valeur"),
            "equipements": ", ".join(donnees.get("equipements", [])),
            "procedes": ", ".join(donnees.get("procedes_materiaux", [])),
        })
    df = pd.DataFrame(lignes)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Informations métier", len(df))
    m2.metric("Contrat", int((df["type_code"] == "CONTRAT").sum()))
    m3.metric("Guide métier", int((df["type_code"] == "GUIDE_METIER").sum()))
    m4.metric("Cas techniques", int((df["type_code"] == "REPORTAGE_TECHNIQUE").sum()))

    st.markdown("### Rechercher une information utile")
    f1, f2, f3 = st.columns(3)
    types = sorted(df["type"].unique())
    categories = sorted(df["categorie"].unique())
    documents = sorted(df["document"].unique())
    filtre_types = f1.multiselect("Famille documentaire", types, default=types)
    filtre_categories = f2.multiselect("Thème métier", categories, default=categories)
    filtre_documents = f3.multiselect("Document", documents, default=documents)
    recherche = st.text_input(
        "Recherche libre",
        placeholder="Ex. paiement, sécurité, rapport de chantier, compactage...",
        key="recherche_documents_metier",
    )
    seulement_verifier = st.checkbox("Afficher uniquement les informations à vérifier")

    filtre = df[
        df["type"].isin(filtre_types)
        & df["categorie"].isin(filtre_categories)
        & df["document"].isin(filtre_documents)
    ].copy()
    if seulement_verifier:
        filtre = filtre[filtre["statut"] == "a_verifier"]
    if recherche:
        colonnes_recherche = ["information", "texte_source", "categorie", "equipements", "procedes"]
        masque = pd.Series(False, index=filtre.index)
        for colonne in colonnes_recherche:
            masque |= filtre[colonne].fillna("").str.contains(recherche, case=False, regex=False)
        filtre = filtre[masque]

    st.caption(f"{len(filtre)} information(s) affichée(s) sur {len(df)}")
    st.dataframe(
        filtre[["type", "document", "page", "categorie", "information", "statut_affiche"]],
        hide_index=True, width="stretch", height=390,
        column_config={
            "type": "Famille", "document": "Document source", "page": "Page",
            "categorie": "Thème métier", "information": "Information détectée",
            "statut_affiche": "Contrôle",
        },
    )

    if filtre.empty:
        st.info("Aucun résultat ne correspond aux filtres. Élargissez la sélection ou effacez la recherche.")
        return

    st.markdown("### Vérifier la preuve dans le document")
    ids = filtre["id"].tolist()
    identifiant = st.selectbox(
        "Information à consulter", ids,
        format_func=lambda ident: next(
            f"{ligne.type} — page {ligne.page} — {ligne.information}"
            for ligne in filtre.itertuples() if ligne.id == ident
        ),
    )
    detail = filtre[filtre["id"] == identifiant].iloc[0]
    c1, c2, c3 = st.columns([2, 1, 1])
    c1.markdown(f"**Document**  \n{detail['document']}")
    c2.markdown(f"**Page**  \n{detail['page']}")
    c3.markdown(f"**Qualité de lecture**  \n{detail['qualite']}")

    afficher_texte_source("Extrait original du PDF (preuve)", detail["texte_source"])
    if detail["equipements"] or detail["procedes"]:
        a, b = st.columns(2)
        a.write(f"**Équipements repérés :** {detail['equipements'] or 'Non détecté'}")
        b.write(f"**Procédés ou matériaux :** {detail['procedes'] or 'Non détecté'}")
    st.markdown("### Exporter les résultats filtrés")
    colonnes_export = ["type", "document", "page", "categorie", "information", "texte_source", "qualite", "statut"]
    e1, e2 = st.columns(2)
    e1.download_button(
        "Télécharger en CSV", filtre[colonnes_export].to_csv(index=False).encode("utf-8-sig"),
        file_name="documents_metier_filtres.csv", mime="text/csv",
    )
    e2.download_button(
        "Télécharger en JSON",
        filtre[colonnes_export].to_json(orient="records", force_ascii=False, indent=2).encode("utf-8"),
        file_name="documents_metier_filtres.json", mime="application/json",
    )


def _chemin_temporaire_pdf(contenu: bytes, nom: str) -> Path:
    dossier = RACINE_PROJET / "tmp" / "analyse_upload"
    dossier.mkdir(parents=True, exist_ok=True)
    fichier = tempfile.NamedTemporaryFile(
        prefix="apercu_", suffix=".pdf", dir=dossier, delete=False
    )
    try:
        fichier.write(contenu)
    finally:
        fichier.close()
    return Path(fichier.name)


@st.cache_data(show_spinner=False)
def _preparer_pdf_importe(contenu: bytes, nom: str) -> tuple[dict, str, list[str]]:
    """Inspecte une seule fois un même fichier, même après les reruns Streamlit."""
    chemin = _chemin_temporaire_pdf(contenu, nom)
    try:
        inspection = inspecter_pdf(chemin)
        proposition, indices = proposer_type(nom, inspection["pages"])
        return inspection, proposition, indices
    finally:
        chemin.unlink(missing_ok=True)


@st.cache_data(show_spinner=False)
def _analyser_pdf_importe(contenu: bytes, nom: str, type_choisi: str) -> dict:
    """Mémorise le résultat afin que les interactions suivantes soient instantanées."""
    chemin = _chemin_temporaire_pdf(contenu, nom)
    try:
        # Les extracteurs utilisent le nom du fichier temporaire. Le nom métier
        # est rétabli dans le résultat présenté à l'utilisateur.
        analyse = analyser_nouveau_document(chemin, type_choisi)
        analyse["nom_fichier"] = nom
        for element in analyse["elements"]:
            element["fichier_source"] = nom
        return analyse
    finally:
        chemin.unlink(missing_ok=True)


def _afficher_resume_nouveau_document(analyse: dict) -> None:
    resume = analyse["resume"]
    type_document = analyse["type_final"]
    libelles_types = {
        "CCTP": "CCTP", "DQE": "DQE", "CONTRAT": "contrat de travaux",
        "GUIDE_METIER": "guide métier", "REPORTAGE_TECHNIQUE": "reportage technique",
        "AUTRE_BTP": "document BTP",
    }
    entites_principales = sorted(resume["entites"].items(), key=lambda x: -x[1])[:3]
    details_entites = ", ".join(
        f"{nombre} occurrence(s) de {categorie.replace('_', ' ')}"
        for categorie, nombre in entites_principales
    )
    if type_document == "DQE":
        controles = resume["controles"]
        detail_controles = ", ".join(
            f"{nombre} {statut.replace('_', ' ')}" for statut, nombre in controles.items()
        )
        phrase_metier = (
            f"Le système a identifié {resume['nombre_elements']} poste(s) de devis"
            + (f", dont {detail_controles}" if detail_controles else "") + "."
        )
    else:
        phrase_metier = (
            f"Le système a détecté {resume['nombre_elements']} extrait(s) métier "
            f"dans ce {libelles_types.get(type_document, 'document BTP')}."
        )
    phrase_nlp = (
        f" Les informations techniques dominantes sont : {details_entites}."
        if details_entites else " Aucune entité technique spécialisée n'a été reconnue."
    )
    st.subheader("Synthèse automatique du document")
    st.markdown(
        f"<div class='status-box'>Le document contient <b>{resume['nombre_pages']} page(s) lisible(s)</b>. "
        f"{phrase_metier}{phrase_nlp}</div>",
        unsafe_allow_html=True,
    )

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Pages lisibles", resume["nombre_pages"])
    col2.metric("Extraits métier détectés", resume["nombre_elements"])
    col3.metric("Catégories trouvées", len(resume["categories"]))
    col4.metric("Familles d'entités NLP", len(resume["entites"]))

    gauche, droite = st.columns(2)
    with gauche:
        st.subheader("Structure métier détectée")
        if resume["categories"]:
            st.dataframe(
                pd.DataFrame(
                    [{"Catégorie": k.replace("_", " ").title(), "Nombre": v}
                     for k, v in sorted(resume["categories"].items(), key=lambda x: -x[1])]
                ), hide_index=True, width="stretch",
            )
        else:
            st.info("Aucune structure métier détectée avec le scénario choisi.")
    with droite:
        st.subheader("Informations techniques reconnues")
        if resume["entites"]:
            st.dataframe(
                pd.DataFrame(
                    [{"Famille NLP": k.replace("_", " ").title(), "Occurrences": v}
                     for k, v in sorted(resume["entites"].items(), key=lambda x: -x[1])]
                ), hide_index=True, width="stretch",
            )
        else:
            st.info("Aucune entité technique reconnue dans les éléments extraits.")

    if resume["controles"]:
        st.subheader("Contrôles métier")
        st.write(" · ".join(f"{statut.replace('_', ' ').title()} : {nombre}"
                            for statut, nombre in resume["controles"].items()))

    st.subheader("Preuves représentatives")
    for passage in resume["passages_representatifs"]:
        titre = f"Page {passage['page']} — {passage.get('libelle') or 'Passage détecté'}"
        with st.expander(titre):
            afficher_texte_source("Texte extrait du PDF", passage["texte_source"])


def page_analyser_document():
    entete()
    st.title("Analyser un document BTP")
    st.markdown(
        """
        <div class="upload-intro">
          <div class="upload-icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" role="img">
              <path d="M6 2.75h8l4 4V21.25H6z" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linejoin="round"/>
              <path d="M14 2.75v4h4M9 12h6M9 15.5h6" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
          </div>
          <div>
            <div class="upload-heading">Déposez votre document technique</div>
            <div class="upload-copy">Le système identifie sa famille, extrait les informations métier et prépare les preuves à vérifier.</div>
          </div>
        </div>
        <div class="upload-steps">
          <div class="upload-step"><b>1 · Importer</b><span>Sélectionnez un fichier PDF.</span></div>
          <div class="upload-step"><b>2 · Vérifier</b><span>Confirmez la famille proposée.</span></div>
          <div class="upload-step"><b>3 · Analyser</b><span>Consultez la synthèse et les preuves.</span></div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    with st.container(key="zone_import_document"):
        fichier = st.file_uploader(
            "Document PDF",
            type=["pdf"],
            accept_multiple_files=False,
            help="Format accepté : PDF, 30 Mo maximum.",
        )
        st.markdown(
            """
            <div class="privacy-note">
              <span aria-hidden="true">⌾</span>
              <span><strong>Traitement local et confidentiel</strong> — aucun contenu n’est envoyé vers un service externe.</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
    if fichier is None:
        return

    contenu = fichier.getvalue()
    if len(contenu) > 30 * 1024 * 1024:
        st.error("Le fichier dépasse la limite de 30 Mo.")
        return
    if not contenu.startswith(b"%PDF"):
        st.error("Le fichier sélectionné n'est pas un PDF valide.")
        return

    try:
        with st.spinner("Lecture et contrôle du PDF…"):
            inspection, propose, indices = _preparer_pdf_importe(contenu, fichier.name)
    except Exception as erreur:
        st.error(f"Lecture impossible : {erreur}")
        return

    document_existant = next(
        (document for document in charger_documents()
         if document.get("sha256") == inspection["sha256"]),
        None,
    )
    if document_existant:
        st.success(
            f"Document déjà présent dans le corpus — dernière analyse : "
            f"{document_existant.get('date_derniere_analyse') or 'non renseignée'}."
        )
    else:
        st.info("Nouveau document — il n'est pas encore enregistré dans le corpus.")

    c1, c2 = st.columns(2)
    c1.metric("Pages", inspection["nombre_pages"])
    c2.metric("Type proposé", propose.replace("_", " "))
    if indices:
        st.caption("Indices utilisés pour la proposition : " + ", ".join(indices))

    types = list(TYPES_DOCUMENT)
    type_choisi = st.selectbox(
        "Famille documentaire à appliquer",
        types,
        index=types.index(propose),
        format_func=lambda valeur: TYPES_DOCUMENT[valeur],
        help="Vous gardez la décision finale : corrigez la proposition si nécessaire.",
    )
    if st.button("Analyser le document", type="primary", icon=":material/document_scanner:"):
        try:
            with st.spinner("Analyse métier et NLP en cours…"):
                analyse = _analyser_pdf_importe(contenu, fichier.name, type_choisi)
            st.session_state["analyse_nouveau_document"] = analyse
            st.session_state["contenu_nouveau_document"] = contenu
            st.session_state["nom_nouveau_document"] = fichier.name
            st.session_state["empreinte_nouveau_document"] = inspection["sha256"]
        except Exception as erreur:
            st.error(f"Analyse impossible : {erreur}")

    analyse = st.session_state.get("analyse_nouveau_document")
    if (
        not analyse
        or st.session_state.get("nom_nouveau_document") != fichier.name
        or st.session_state.get("empreinte_nouveau_document") != inspection["sha256"]
    ):
        return
    st.success(f"Analyse terminée avec le scénario {TYPES_DOCUMENT[analyse['type_final']] }.")
    _afficher_resume_nouveau_document(analyse)
    action_actualisation = document_existant is not None
    st.subheader("Actualiser l'analyse" if action_actualisation else "Choisir l'intégration du document")
    if not analyse["integrable"]:
        st.info("Cette famille ne peut pas encore être conservée dans le corpus local.")
        return
    if action_actualisation:
        categorie_enregistree = document_existant.get("categorie_metier")
        if categorie_enregistree in TYPES_DOCUMENT and categorie_enregistree != analyse["type_final"]:
            st.warning(
                f"Le document est enregistré comme {categorie_enregistree}. "
                "L'actualisation conservera cette famille documentaire."
            )
        texte_confirmation = "Je confirme l'actualisation de l'analyse de ce document."
    else:
        texte_confirmation = "Je confirme la famille documentaire choisie pour ce PDF."

    confirmer = st.checkbox(texte_confirmation)

    if action_actualisation:
        lancer_analyse = st.button(
            "Actualiser l'analyse du document", disabled=not confirmer,
            type="primary", icon=":material/refresh:",
        )
        annuler = False
        stocker_seulement = False
    else:
        st.caption(
            "Le PDF sera conservé avec le statut « Importé — analyse à lancer »."
        )
        col_stockage, col_annuler = st.columns([1.25, .75])
        stocker_seulement = col_stockage.button(
            "Ajouter au corpus", disabled=not confirmer,
            type="primary", icon=":material/library_add:",
        )
        lancer_analyse = False
        annuler = col_annuler.button("Annuler", icon=":material/close:")

    if annuler:
        for cle in ("analyse_nouveau_document", "contenu_nouveau_document",
                    "nom_nouveau_document", "empreinte_nouveau_document"):
            st.session_state.pop(cle, None)
        st.rerun()

    if stocker_seulement or lancer_analyse:
        if action_actualisation:
            destination = RACINE_PROJET / document_existant["chemin_relatif"]
        else:
            dossier = RACINE_PROJET / "data" / DOSSIERS_CORPUS[analyse["type_final"]]
            dossier.mkdir(parents=True, exist_ok=True)
            destination = dossier / nom_securise(fichier.name)
            if destination.exists() and destination.read_bytes() != contenu:
                destination = dossier / f"{destination.stem}_{analyse['inspection']['sha256'][:8]}.pdf"
            destination.write_bytes(contenu)

        if stocker_seulement:
            try:
                enregistrer_document_seul(destination)
                st.cache_data.clear()
                st.success("Document ajouté au corpus avec le statut « Importé — analyse à lancer ».")
                st.caption(
                    "Le PDF source est conservé sans modification. "
                    f"Emplacement local : {destination.relative_to(RACINE_PROJET).as_posix()}"
                )
            except Exception as erreur:
                st.error(f"Le document n'a pas pu être enregistré : {erreur}")
            return

        try:
            with st.spinner("Actualisation ciblée de ce document…"):
                resultat_cible = actualiser_document_cible(destination, analyse["elements"])
            st.cache_data.clear()
            resume = analyse["resume"]
            st.success("Analyse du document actualisée avec succès.")
            b1, b2, b3 = st.columns(3)
            b1.metric("Éléments analysés", resultat_cible["elements"])
            b2.metric("Familles NLP", len(resume["entites"]))
            b3.metric("À vérifier", sum(
                nombre for statut, nombre in resume["controles"].items()
                if statut in {"incomplet", "a_verifier"}
            ))
            st.caption(
                "Mise à jour ciblée : 1 document traité · "
                f"{resultat_cible['validations_preservees']} validation(s) humaine(s) préservée(s)."
            )
            st.caption(f"Emplacement local : {destination.relative_to(RACINE_PROJET).as_posix()}")
        except Exception as erreur:
            st.error("Le document est conservé, mais son actualisation ciblée a rencontré une erreur.")
            with st.expander("Détail technique"):
                st.code(str(erreur))

def page_rapprochement():
    entete()
    st.subheader("Rapprochement intelligent CCTP ↔ DQE")
    rapprochements = charger_rapprochements()
    if not rapprochements:
        st.warning("Aucun rapprochement enregistré. Lancez python src\\run_pipeline.py")
        return
    confirmation = st.session_state.pop("confirmation_rapprochement", None)
    if confirmation:
        st.success(confirmation)

    df = pd.DataFrame(rapprochements)
    avec_candidat = df[df["extraction_cctp_id"].notna()].copy()
    sans_candidat = df[df["extraction_cctp_id"].isna()].copy()
    postes_avec = avec_candidat["extraction_dqe_id"].nunique()
    validations = int(avec_candidat["decision_humaine"].isin(["accepte", "rejete"]).sum())

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Postes DQE analysés", df["extraction_dqe_id"].nunique())
    m2.metric("Postes avec candidat", postes_avec)
    m3.metric("Sans correspondance", sans_candidat["extraction_dqe_id"].nunique())
    m4.metric("Propositions validées", f"{validations} / {len(avec_candidat)}")

    noms_niveaux = {
        "forte": "Forte", "moyenne": "Moyenne", "faible": "Faible",
        "sans_correspondance": "Sans correspondance",
    }
    noms_decisions = {
        "a_valider": "À valider", "accepte": "Acceptée", "rejete": "Rejetée",
        "non_requise": "Non requise",
    }
    df["niveau_affiche"] = df["niveau"].map(noms_niveaux).fillna(df["niveau"])
    df["decision_affichee"] = df["decision_humaine"].map(noms_decisions).fillna(df["decision_humaine"])
    df["score_pourcent"] = df["score"].fillna(0).mul(100).round(1)

    decisions_enregistrees = df[df["decision_humaine"].isin(["accepte", "rejete"])]
    if not decisions_enregistrees.empty:
        with st.expander(f"Décisions enregistrées ({len(decisions_enregistrees)})"):
            historique = decisions_enregistrees.copy()
            historique["poste_dqe"] = historique.apply(
                lambda r: f"{r['dqe_numero_poste'] or '-'} · {r['dqe_libelle']}", axis=1
            )
            st.dataframe(
                historique[["poste_dqe", "cctp_libelle", "score_pourcent", "decision_affichee", "commentaire"]],
                hide_index=True, width="stretch",
                column_config={
                    "poste_dqe": "Poste DQE", "cctp_libelle": "Prescription CCTP",
                    "score_pourcent": "Score (%)", "decision_affichee": "Décision",
                    "commentaire": "Commentaire",
                },
            )

    st.markdown("### Explorer les propositions")
    f1, f2, f3 = st.columns(3)
    documents = sorted(df["dqe_document"].dropna().unique())
    niveaux = sorted(df["niveau_affiche"].dropna().unique())
    decisions = sorted(df["decision_affichee"].dropna().unique())
    filtre_documents = f1.multiselect("Document DQE", documents, default=documents)
    filtre_niveaux = f2.multiselect("Niveau", niveaux, default=niveaux)
    filtre_decisions = f3.multiselect("Décision", decisions, default=decisions)
    recherche = st.text_input(
        "Rechercher dans les deux descriptions",
        placeholder="Ex. béton armé, canalisation, peinture...",
        key="recherche_rapprochement",
    )
    filtre = df[
        df["dqe_document"].isin(filtre_documents)
        & df["niveau_affiche"].isin(filtre_niveaux)
        & df["decision_affichee"].isin(filtre_decisions)
    ].copy()
    if recherche:
        masque = (
            filtre["dqe_libelle"].fillna("").str.contains(recherche, case=False, regex=False)
            | filtre["cctp_libelle"].fillna("").str.contains(recherche, case=False, regex=False)
            | filtre["dqe_texte_source"].fillna("").str.contains(recherche, case=False, regex=False)
            | filtre["cctp_texte_source"].fillna("").str.contains(recherche, case=False, regex=False)
        )
        filtre = filtre[masque]

    st.caption(f"{len(filtre)} ligne(s) affichée(s) sur {len(df)}")
    tableau = filtre.copy()
    tableau["poste_dqe"] = tableau.apply(
        lambda r: f"{r['dqe_numero_poste'] or '-'} · {r['dqe_libelle']}", axis=1
    )
    tableau["prescription_cctp"] = tableau["cctp_libelle"].fillna("Aucun candidat suffisamment fiable")
    st.dataframe(
        tableau[["poste_dqe", "prescription_cctp", "score_pourcent", "niveau_affiche", "decision_affichee"]],
        hide_index=True, width="stretch", height=390,
        column_config={
            "poste_dqe": "Poste DQE", "prescription_cctp": "Prescription CCTP proposée",
            "score_pourcent": st.column_config.ProgressColumn(
                "Score", help="Score d'aide au tri, à confirmer humainement", min_value=0, max_value=100, format="%.1f %%"
            ),
            "niveau_affiche": "Niveau", "decision_affichee": "Décision",
        },
    )

    candidats_filtrees = filtre[filtre["extraction_cctp_id"].notna()]
    if candidats_filtrees.empty:
        st.info("Aucune proposition à valider dans cette sélection.")
        return

    st.markdown("### Comparer et décider")
    identifiants = candidats_filtrees["id"].tolist()
    identifiant = st.selectbox(
        "Proposition à examiner", identifiants,
        format_func=lambda ident: next(
            f"Poste {r.dqe_numero_poste or '-'} — {r.dqe_libelle} — candidat {r.rang_candidat}"
            for r in candidats_filtrees.itertuples() if r.id == ident
        ),
    )
    detail = next(r for r in rapprochements if r["id"] == identifiant)
    score = float(detail["score"] or 0)
    a, b, c = st.columns(3)
    a.metric("Score de correspondance", f"{score * 100:.1f} %")
    b.metric("Niveau", noms_niveaux.get(detail["niveau"], detail["niveau"]))
    c.metric("Rang du candidat", detail["rang_candidat"])

    gauche, droite = st.columns(2)
    with gauche:
        st.markdown("#### Poste DQE")
        st.write(f"**Document :** {detail['dqe_document']}")
        st.write(f"**Page / poste :** {detail['dqe_page']} / {detail['dqe_numero_poste'] or '-'}")
        st.write(f"**Désignation :** {detail['dqe_libelle']}")
        afficher_texte_source("Texte source DQE", detail["dqe_texte_source"])
    with droite:
        st.markdown("#### Prescription CCTP proposée")
        st.write(f"**Document :** {detail['cctp_document']}")
        st.write(f"**Page / section :** {detail['cctp_page']} / {detail['cctp_section'] or '-'}")
        st.write(f"**Libellé :** {detail['cctp_libelle']}")
        afficher_texte_source("Texte source CCTP", detail["cctp_texte_source"])

    justification = detail.get("justification", {})
    mots = justification.get("mots_techniques_communs", [])
    entites = justification.get("entites_communes", [])
    st.markdown(
        f"**Pourquoi cette proposition ?** Mots techniques communs : "
        f"`{', '.join(mots) if mots else 'aucun mot discriminant'}`. "
        f"Entités communes : `{', '.join(entites) if entites else 'aucune'}`."
    )

    choix_decisions = ["À valider", "Accepter", "Refuser"]
    index_decision = {"a_valider": 0, "accepte": 1, "rejete": 2}.get(detail["decision_humaine"], 0)
    decision_ui = st.radio(
        "Décision du technicien", choix_decisions, index=index_decision,
        horizontal=True, key=f"decision_rapprochement_{identifiant}",
    )
    commentaire = st.text_area(
        "Commentaire (facultatif)", value=detail.get("commentaire") or "",
        placeholder="Ex. correspondance validée sur le matériau et la fonction.",
        key=f"commentaire_rapprochement_{identifiant}",
    )
    if st.button("Enregistrer la décision", type="primary", key=f"sauver_rapprochement_{identifiant}"):
        code_decision = {"À valider": "a_valider", "Accepter": "accepte", "Refuser": "rejete"}[decision_ui]
        enregistrer_decision_rapprochement(identifiant, code_decision, commentaire)
        charger_rapprochements.clear()
        st.session_state.confirmation_rapprochement = (
            f"Décision « {decision_ui} » enregistrée. Elle apparaît maintenant dans l'historique ci-dessous."
        )
        st.rerun()


def page_qualite_nlp():
    entete()
    st.subheader("Qualité du NLP et suivi des contrôles")
    validations = charger_validations()
    if not validations:
        st.warning("Aucun échantillon de validation n'est disponible.")
        return

    rapport = evaluer_annotations(validations)
    avancement = rapport["avancement"]
    metriques = rapport["metriques_globales"]
    controles = [
        element for element in validations
        if element.get("validation", {}).get("statut") in {"valide", "corrige"}
    ]
    valides = sum(
        element["validation"]["statut"] == "valide" for element in controles
    )
    corriges = sum(
        element["validation"]["statut"] == "corrige" for element in controles
    )

    a, b, c, d = st.columns(4)
    a.metric("Contrôles réalisés", f"{avancement['valides']} / {avancement['total']}")
    b.metric("Validés sans correction", valides)
    c.metric("Contrôles corrigés", corriges)
    d.metric("Reste à contrôler", avancement["total"] - avancement["valides"])
    st.progress(
        avancement["pourcentage"] / 100,
        text=f"Avancement de la validation humaine : {avancement['pourcentage']:.1f} %",
    )
    st.caption(
        "Couverture de l’évaluation : "
        f"{avancement['valides']} / {avancement['total']} extraits "
        f"({avancement['pourcentage']:.1f} %)."
    )

    st.markdown("### Performance sur l'échantillon contrôlé")
    p, r, f = st.columns(3)
    p.metric("Précision", f"{100 * metriques['precision']:.1f} %")
    r.metric("Rappel", f"{100 * metriques['rappel']:.1f} %")
    f.metric("Score F1", f"{100 * metriques['f1']:.1f} %")
    e, o, detections = st.columns(3)
    e.metric("Erreurs signalées", metriques["faux_positifs"])
    o.metric("Informations oubliées", metriques["faux_negatifs"])
    detections.metric("Entités correctement détectées", metriques["vrais_positifs"])

    st.info(
        "Les performances sont calculées uniquement sur l’échantillon validé "
        "manuellement. Elles évolueront à mesure que les contrôles progresseront."
    )

    if rapport["par_categorie"]:
        noms_categories = {
            "materiaux": "Matériaux", "ouvrages_equipements": "Ouvrages / équipements",
            "normes": "Normes", "classes_beton": "Classes de béton",
            "resistances": "Résistances", "dosages": "Dosages",
            "diametres": "Diamètres", "epaisseurs": "Épaisseurs",
            "dimensions": "Dimensions", "mesures": "Mesures",
            "proprietes": "Propriétés", "type_ciment": "Type de ciment",
        }
        lignes = []
        for categorie, valeurs in rapport["par_categorie"].items():
            lignes.append({
                "Catégorie": noms_categories.get(categorie, categorie),
                "Correctes": valeurs["vrais_positifs"],
                "Incorrectes": valeurs["faux_positifs"],
                "Oubliées": valeurs["faux_negatifs"],
                "Précision": f"{100 * valeurs['precision']:.1f} %",
                "Rappel": f"{100 * valeurs['rappel']:.1f} %",
                "F1": f"{100 * valeurs['f1']:.1f} %",
            })

        st.markdown("### Qualité par catégorie technique")
        graphique = pd.DataFrame(lignes).sort_values("Correctes", ascending=True)
        maximum = max(
            1,
            int(
                graphique[["Correctes", "Incorrectes", "Oubliées"]]
                .sum(axis=1)
                .max()
            ),
        )
        barres = []
        for _, ligne in graphique.iterrows():
            total = max(
                1,
                int(ligne["Correctes"] + ligne["Incorrectes"] + ligne["Oubliées"]),
            )
            largeur_totale = 100 * total / maximum
            segments = []
            for champ, couleur in (
                ("Correctes", "#2f855a"),
                ("Incorrectes", "#a61f2b"),
                ("Oubliées", "#d97706"),
            ):
                valeur = int(ligne[champ])
                if valeur:
                    segments.append(
                        f'<span title="{champ} : {valeur}" '
                        f'style="display:block;width:{100 * valeur / total:.1f}%;'
                        f'background:{couleur};height:12px"></span>'
                    )
            barres.append(
                '<div style="display:grid;grid-template-columns:190px 1fr 42px;'
                'gap:12px;align-items:center;margin:10px 0">'
                f'<span>{html.escape(str(ligne["Catégorie"]))}</span>'
                '<div style="background:#f1e7e8;border-radius:999px;overflow:hidden">'
                f'<div style="display:flex;width:{largeur_totale:.1f}%">'
                + "".join(segments)
                + '</div></div>'
                f'<strong>{total}</strong></div>'
            )
        st.markdown(
            '<div style="display:flex;gap:20px;margin-bottom:8px;font-size:.9rem">'
            '<span style="color:#2f855a">● Correctes</span>'
            '<span style="color:#a61f2b">● Incorrectes</span>'
            '<span style="color:#d97706">● Oubliées</span></div>'
            + "".join(barres),
            unsafe_allow_html=True,
        )

        with st.expander("Consulter le détail chiffré par catégorie"):
            st.dataframe(graphique, hide_index=True, width="stretch")

    with st.expander("Comment lire ces indicateurs ?"):
        st.markdown(
            """
            - **Précision** : parmi les informations trouvées par le NLP, part de celles qui sont correctes.
            - **Rappel** : parmi les informations présentes dans le texte, part de celles que le NLP a retrouvées.
            - **Score F1** : synthèse équilibrée de la précision et du rappel.
            - **Contrôle corrigé** : au moins une erreur ou une information oubliée a été signalée.
            """
        )


def page_validation_metier():
    elements_metier = [
        {**element, "source_validation": "metier"}
        for element in lister_validations_metier()
    ]
    elements_techniques = [
        {**element, "source_validation": "technique"}
        for element in lister_validations_extractions()
    ]
    elements = elements_metier + elements_techniques
    noms_categories = {
        "identification": "Identification",
        "parties": "Parties et intervenants",
        "parties_intervenants": "Parties et intervenants",
        "objet_travaux": "Objet et travaux",
        "prix": "Prix",
        "paiement": "Paiement et prix",
        "paiement_prix": "Paiement et prix",
        "modifications": "Modifications",
        "suspension": "Suspension",
        "sous_traitance_securite": "Sous-traitance et sécurité",
        "securite_prevention": "Sécurité et prévention",
        "delais_penalites": "Délais et pénalités",
        "garantie": "Garantie",
        "garantie_assurance": "Garantie et assurance",
        "resiliation": "Résiliation",
        "resiliation_differends": "Résiliation et différends",
        "loi_differends": "Loi et différends",
        "clause_generale": "Clause générale",
        "document_suivi": "Document de suivi",
        "obligation": "Obligations",
        "obligations": "Obligations",
        "recommandation": "Recommandation",
        "risque_preuve": "Risques, preuves et réclamations",
        "cas_chantier_technique": "Cas de chantier technique",
        "qualite_controle": "Qualité et contrôle",
        "normes_references": "Normes et références",
        "materiaux_ouvrages": "Matériaux et ouvrages",
        "quantites_dimensions": "Quantités et dimensions",
        "avancement_incidents": "Avancement et incidents",
        "environnement_dechets": "Environnement et déchets",
        "mise_en_oeuvre": "Mise en œuvre",
        "fourniture_pose": "Fourniture et pose",
        "terrassement_fondations": "Terrassements et fondations",
        "beton_armatures": "Béton et armatures",
        "tolerances_performances": "Tolérances et performances",
    }

    def nom_categorie(code: str) -> str:
        return noms_categories.get(code, code.replace("_", " ").capitalize())

    en_attente = [e for e in elements if e["statut_validation"] == "a_verifier" and not e.get("decision")]
    controles = [e for e in elements if e.get("decision")]

    a, b, c, d = st.columns(4)
    a.metric("À vérifier", len(en_attente))
    b.metric("Validés", sum(e.get("decision") == "valide" for e in controles))
    c.metric("Corrigés", sum(e.get("decision") == "corrige" for e in controles))
    d.metric("Rejetés", sum(e.get("decision") == "rejete" for e in controles))

    confirmation = st.session_state.pop("confirmation_validation_metier", None)
    if confirmation:
        st.success(confirmation)

    if controles:
        noms_decisions = {"valide": "Validé", "corrige": "Corrigé", "rejete": "Rejeté"}
        historique = pd.DataFrame([
            {
                "Document": e["nom_fichier"], "Page": e["page"],
                "Information initiale": e.get("ancienne_valeur") or e["libelle"],
                "Décision": noms_decisions.get(e["decision"], e["decision"]),
                "Résultat final": e.get("nouvelle_valeur") or "—",
                "Commentaire": e.get("commentaire_controle") or "—",
                "Date": e.get("date_controle") or "—",
            }
            for e in reversed(controles)
        ])
        with st.expander(f"Historique des contrôles métier ({len(controles)})"):
            st.dataframe(historique, hide_index=True, width="stretch")

    if not en_attente:
        st.success("Aucun nouvel extrait métier n'attend une validation.")
        return

    documents = sorted({e["nom_fichier"] for e in en_attente})
    categories = sorted({e["categorie"] for e in en_attente})
    col_doc, col_cat = st.columns(2)
    document = col_doc.selectbox("Document à contrôler", ["Tous"] + documents)
    categorie = col_cat.selectbox(
        "Catégorie métier", ["Toutes"] + categories,
        format_func=lambda code: code if code == "Toutes" else nom_categorie(code),
    )
    file_filtree = [
        e for e in en_attente
        if (document == "Tous" or e["nom_fichier"] == document)
        and (categorie == "Toutes" or e["categorie"] == categorie)
    ]
    if not file_filtree:
        st.info("Aucun extrait ne correspond à ces filtres.")
        return

    identifiants = [f"{e['source_validation']}:{e['id']}" for e in file_filtree]
    selection = st.selectbox(
        "Extrait à contrôler",
        identifiants,
        format_func=lambda cle: next(
            f"{e['nom_fichier']} — page {e['page']} — {nom_categorie(e['categorie'])} — {e['libelle']}"
            for e in file_filtree
            if f"{e['source_validation']}:{e['id']}" == cle
        ),
    )
    element = next(
        e for e in file_filtree
        if f"{e['source_validation']}:{e['id']}" == selection
    )
    col1, col2, col3 = st.columns([3, 1, 2])
    col1.markdown(f"**Document**  \n{element['nom_fichier']}")
    col2.markdown(f"**Page**  \n{element['page'] or '—'}")
    col3.markdown(f"**Thème proposé**  \n{nom_categorie(element['categorie'])}")
    afficher_texte_source("Preuve extraite du PDF", element.get("texte_source") or "")

    decision_affichee = st.radio(
        "Décision du technicien",
        ["Valider", "Corriger", "Rejeter"],
        horizontal=True,
        key=f"decision_metier_{selection.replace(':', '_')}",
    )
    nouvelle_categorie = element["categorie"]
    nouvelle_valeur = element["libelle"]
    if decision_affichee == "Corriger":
        categories_connues = sorted({e["categorie"] for e in elements} | {element["categorie"]})
        nouvelle_categorie = st.selectbox(
            "Catégorie corrigée", categories_connues,
            index=categories_connues.index(element["categorie"]),
            format_func=nom_categorie,
            key=f"categorie_metier_{selection.replace(':', '_')}",
        )
        nouvelle_valeur = st.text_input(
            "Information corrigée", value=element["libelle"],
            key=f"valeur_metier_{selection.replace(':', '_')}",
        )
    commentaire = st.text_area(
        "Commentaire (facultatif)",
        placeholder="Ex. clause confirmée dans le texte source.",
        key=f"commentaire_metier_{selection.replace(':', '_')}",
    )
    if st.button("Enregistrer la décision métier", type="primary"):
        decisions = {"Valider": "valide", "Corriger": "corrige", "Rejeter": "rejete"}
        try:
            fonction_enregistrement = (
                enregistrer_validation_metier
                if element["source_validation"] == "metier"
                else enregistrer_validation_extraction
            )
            resultat = fonction_enregistrement(
                element["id"], decisions[decision_affichee],
                nouvelle_categorie, nouvelle_valeur, commentaire,
            )
            st.session_state.confirmation_validation_metier = (
                f"Décision enregistrée : {decision_affichee.lower()}. "
                "Le contrôle est conservé dans l'historique."
            )
            st.rerun()
        except ValueError as erreur:
            st.error(str(erreur))


def page_validation_nlp_existante():
    st.markdown(
        """
        <style>
        .nlp-control-hero {
            padding: 1.15rem 1.3rem;
            margin: .35rem 0 1.15rem 0;
            border: 1px solid #efd0d4;
            border-left: 5px solid #b82431;
            border-radius: 16px;
            background: linear-gradient(135deg, #fffafb 0%, #f9e9eb 100%);
            box-shadow: 0 8px 22px rgba(83, 25, 31, .07);
        }
        .nlp-control-hero h2 {
            color: #28282b;
            margin: 0 0 .35rem 0;
            font-size: 1.75rem;
        }
        .nlp-control-hero p {
            color: #62646a;
            margin: 0;
            line-height: 1.55;
        }
        .nlp-workflow {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: .75rem;
            margin-top: 1rem;
        }
        .nlp-workflow-step {
            background: rgba(255, 255, 255, .82);
            border: 1px solid #ecdadd;
            border-radius: 12px;
            padding: .8rem .9rem;
            color: #3f3f43;
            font-size: .92rem;
        }
        .nlp-workflow-step strong {
            display: block;
            color: #9f1f2b;
            margin-bottom: .18rem;
        }
        .nlp-section-title {
            display: flex;
            align-items: center;
            gap: .65rem;
            margin: 1.45rem 0 .65rem 0;
            color: #29292d;
            font-size: 1.45rem;
            font-weight: 750;
        }
        .nlp-section-number {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 2rem;
            height: 2rem;
            border-radius: 10px;
            color: white;
            background: linear-gradient(135deg, #7c1d27, #c32634);
            box-shadow: 0 5px 12px rgba(155, 31, 42, .22);
            font-size: .95rem;
        }
        @media (max-width: 850px) {
            .nlp-workflow { grid-template-columns: 1fr; }
        }
        </style>
        <section class="nlp-control-hero">
            <h2>Contrôle qualité des informations détectées</h2>
            <p>Le technicien compare les informations proposées par le NLP avec le passage original du PDF, puis valide ou corrige le résultat sans modifier le document source.</p>
            <div class="nlp-workflow">
                <div class="nlp-workflow-step"><strong>1 · Lire la preuve</strong>Consulter le passage exact extrait du PDF.</div>
                <div class="nlp-workflow-step"><strong>2 · Contrôler le NLP</strong>Vérifier les entités détectées et les éventuels oublis.</div>
                <div class="nlp-workflow-step"><strong>3 · Enregistrer</strong>Conserver la décision et la correction dans l’historique.</div>
            </div>
        </section>
        """,
        unsafe_allow_html=True,
    )
    validations = charger_validations()
    if not validations:
        st.warning("Aucun échantillon disponible. Lancez python src\\preparer_validation_nlp.py")
        return

    terminees = sum(v["validation"]["statut"] != "a_valider" for v in validations)
    st.progress(terminees / len(validations), text=f"Avancement : {terminees} / {len(validations)}")

    confirmation = st.session_state.pop("confirmation_validation_nlp", None)
    if confirmation:
        st.success(confirmation)

    controles_enregistres = [
        element for element in validations
        if element.get("validation", {}).get("statut") != "a_valider"
    ]
    if controles_enregistres:
        noms_statuts = {"valide": "Validé", "corrige": "Corrigé"}

        def compter_valeurs(groupes):
            if not isinstance(groupes, dict):
                return 0
            return sum(
                len(valeurs) if isinstance(valeurs, list) else 1
                for valeurs in groupes.values()
            )

        historique = []
        for element in reversed(controles_enregistres):
            controle = element.get("validation", {})
            historique.append({
                "N°": element.get("id_validation"),
                "Document": element.get("fichier_source", ""),
                "Type": element.get("type_document", ""),
                "Page": element.get("page", ""),
                "Élément contrôlé": element.get("libelle", ""),
                "Statut": noms_statuts.get(
                    controle.get("statut"), controle.get("statut", "")
                ),
                "Erreurs signalées": compter_valeurs(
                    controle.get("predictions_incorrectes", {})
                ),
                "Oublis ajoutés": compter_valeurs(
                    controle.get("entites_manquantes", {})
                ),
                "Commentaire": controle.get("commentaire") or "—",
                "Date": controle.get("date_validation", "—"),
            })

        with st.expander(f"Historique des contrôles enregistrés ({len(historique)})"):
            st.dataframe(
                pd.DataFrame(historique), hide_index=True, width="stretch"
            )
            controles_corriges = [
                element for element in controles_enregistres
                if element.get("validation", {}).get("statut") == "corrige"
            ]
            if controles_corriges:
                ids_corriges = [element["id_validation"] for element in controles_corriges]
                correction_choisie = st.selectbox(
                    "Consulter le détail d'une correction",
                    ids_corriges,
                    format_func=lambda identifiant: next(
                        f"{element['id_validation']:02d} - {element['fichier_source']} "
                        f"- page {element['page']}"
                        for element in controles_corriges
                        if element["id_validation"] == identifiant
                    ),
                    key="detail_historique_validation_nlp",
                )
                element_corrige = next(
                    element for element in controles_corriges
                    if element["id_validation"] == correction_choisie
                )
                controle_corrige = element_corrige["validation"]
                categories_historique = {
                    "materiaux": "Matériaux",
                    "ouvrages_equipements": "Ouvrages / équipements",
                    "normes": "Normes",
                    "classes_beton": "Classes de béton",
                    "resistances": "Résistances",
                    "dosages": "Dosages",
                    "diametres": "Diamètres",
                    "epaisseurs": "Épaisseurs",
                    "dimensions": "Dimensions",
                    "mesures": "Mesures",
                    "proprietes": "Propriétés",
                    "type_ciment": "Type de ciment",
                }

                def lignes_entites(groupes: dict, nom_colonne: str) -> list[dict]:
                    return [
                        {
                            "Catégorie": categories_historique.get(categorie, categorie),
                            nom_colonne: (
                                f"{valeur.get('valeur')} {valeur.get('unite', '')}".strip()
                                if isinstance(valeur, dict) and "valeur" in valeur
                                else str(valeur)
                            ),
                        }
                        for categorie, valeurs in groupes.items()
                        for valeur in valeurs
                    ]

                resultat_final = controle_corrige.get("entites_corrigees")
                if resultat_final is None:
                    resultat_final = construire_entites_corrigees(
                        element_corrige.get("predictions_nlp", {}),
                        controle_corrige.get("predictions_incorrectes", {}),
                        controle_corrige.get("entites_manquantes", {}),
                    )
                onglet_retraits, onglet_ajouts, onglet_final = st.tabs(
                    ["Valeurs retirées", "Valeurs ajoutées", "Résultat final corrigé"]
                )
                retraits = lignes_entites(
                    controle_corrige.get("predictions_incorrectes", {}),
                    "Valeur retirée",
                )
                ajouts = lignes_entites(
                    controle_corrige.get("entites_manquantes", {}),
                    "Valeur ajoutée",
                )
                final = lignes_entites(resultat_final, "Valeur validée")
                with onglet_retraits:
                    if retraits:
                        st.dataframe(pd.DataFrame(retraits), hide_index=True, width="stretch")
                    else:
                        st.write("Aucune valeur retirée.")
                with onglet_ajouts:
                    if ajouts:
                        st.dataframe(pd.DataFrame(ajouts), hide_index=True, width="stretch")
                    else:
                        st.write("Aucune valeur ajoutée.")
                with onglet_final:
                    st.dataframe(pd.DataFrame(final), hide_index=True, width="stretch")

    ids = [v["id_validation"] for v in validations]
    selection = st.selectbox(
        "Exemple à contrôler",
        ids,
        format_func=lambda identifiant: next(
            f"{identifiant:02d} - {v['type_document']} - page {v['page']} - {v['validation']['statut']}"
            for v in validations if v["id_validation"] == identifiant
        ),
    )
    annotation = next(v for v in validations if v["id_validation"] == selection)
    c_document, c_page, c_statut = st.columns([3, 1, 1])
    c_document.markdown(f"**Document**  \n{annotation['fichier_source']}")
    c_page.markdown(f"**Page**  \n{annotation['page']}")
    c_statut.markdown(f"**Statut**  \n{annotation['validation']['statut']}")
    st.markdown(f"**Élément analysé :** {annotation['libelle']}")
    afficher_texte_source(
        "Texte original extrait du PDF", formater_source_validation(annotation)
    )

    predictions = annotation.get("predictions_nlp", {})
    validation = annotation.get("validation", {})
    incorrectes_existantes = validation.get("predictions_incorrectes", {})
    nouvelles_incorrectes: dict[str, list] = {}

    noms_categories = {
        "materiaux": "Matériaux", "ouvrages_equipements": "Ouvrages / équipements",
        "normes": "Normes", "classes_beton": "Classes de béton",
        "resistances": "Résistances", "dosages": "Dosages",
        "diametres": "Diamètres", "epaisseurs": "Épaisseurs",
        "dimensions": "Dimensions", "mesures": "Mesures",
        "proprietes": "Propriétés", "type_ciment": "Type de ciment",
    }

    def afficher_valeur(valeur):
        if isinstance(valeur, dict) and "valeur" in valeur:
            nombre = valeur["valeur"]
            nombre = int(nombre) if isinstance(nombre, float) and nombre.is_integer() else nombre
            return f"{nombre} {valeur.get('unite', '')}".strip()
        return str(valeur)

    st.markdown("### Informations détectées par le NLP")
    if not predictions:
        st.warning("Aucune information technique détectée dans cet extrait.")
    else:
        lignes_predictions = [
            {"Catégorie": noms_categories.get(categorie, categorie), "Valeur détectée": afficher_valeur(valeur)}
            for categorie, valeurs in predictions.items() for valeur in valeurs
        ]
        st.dataframe(
            pd.DataFrame(lignes_predictions), hide_index=True,
            width="stretch",
        )

    toutes_correctes = st.radio(
        "1. Toutes les informations affichées sont-elles réellement présentes dans le texte ?",
        ["Oui, elles sont correctes", "Non, certaines sont incorrectes"],
        index=1 if incorrectes_existantes else 0,
        horizontal=True,
        key=f"toutes_correctes_{selection}",
    )
    categories_a_afficher = predictions.items() if toutes_correctes.startswith("Non") else []
    for categorie, valeurs in categories_a_afficher:
        etiquettes = [
            json.dumps(valeur, ensure_ascii=False, sort_keys=True)
            if isinstance(valeur, dict) else str(valeur)
            for valeur in valeurs
        ]
        existantes = {
            json.dumps(valeur, ensure_ascii=False, sort_keys=True)
            if isinstance(valeur, dict) else str(valeur)
            for valeur in incorrectes_existantes.get(categorie, [])
        }
        choisies = st.multiselect(
            f"Sélectionnez les valeurs incorrectes — {noms_categories.get(categorie, categorie)}",
            etiquettes,
            default=[etiquette for etiquette in etiquettes if etiquette in existantes],
            key=f"incorrectes_{selection}_{categorie}",
        )
        if choisies:
            correspondance = dict(zip(etiquettes, valeurs))
            nouvelles_incorrectes[categorie] = [correspondance[valeur] for valeur in choisies]

    manquantes_existantes = validation.get("entites_manquantes", {})
    a_des_oublis = st.radio(
        "2. Le texte contient-il une information technique importante oubliée par le NLP ?",
        ["Non, rien ne manque", "Oui, une information manque"],
        index=1 if manquantes_existantes else 0,
        horizontal=True,
        key=f"a_des_oublis_{selection}",
    )
    if a_des_oublis.startswith("Oui"):
        texte_manquantes = st.text_area(
            "Informations oubliées",
            value=formater_entites_manquantes(manquantes_existantes),
            placeholder="proprietes: hydrofugé\ntype_ciment: CPJ",
            key=f"manquantes_{selection}",
        )
    else:
        texte_manquantes = ""

    try:
        manquantes_apercu = parser_entites_manquantes(texte_manquantes)
    except ValueError:
        manquantes_apercu = {}
    entites_corrigees_apercu = construire_entites_corrigees(
        predictions, nouvelles_incorrectes, manquantes_apercu
    )
    if nouvelles_incorrectes or manquantes_apercu:
        st.markdown("### Résultat corrigé automatiquement")
        lignes_corrigees = [
            {
                "Catégorie": noms_categories.get(categorie, categorie),
                "Valeur validée": afficher_valeur(valeur),
            }
            for categorie, valeurs in entites_corrigees_apercu.items()
            for valeur in valeurs
        ]
        st.dataframe(
            pd.DataFrame(lignes_corrigees), hide_index=True, width="stretch"
        )

    commentaire = st.text_area(
        "3. Commentaire (facultatif)", value=validation.get("commentaire", ""),
        placeholder="À utiliser seulement pour expliquer un cas ambigu.",
        key=f"commentaire_{selection}",
    )
    avait_corrections = bool(
        validation.get("predictions_incorrectes") or validation.get("entites_manquantes")
    )
    autoriser_effacement = False
    if avait_corrections:
        autoriser_effacement = st.checkbox(
            "Je confirme la suppression des corrections déjà enregistrées",
            key=f"effacement_{selection}",
        )
    if st.button("Enregistrer ce contrôle", type="primary"):
        try:
            manquantes = parser_entites_manquantes(texte_manquantes)
            resultat = sauvegarder_validation(
                selection, nouvelles_incorrectes, manquantes, commentaire,
                autoriser_effacement=autoriser_effacement,
            )
            statut_affiche = {
                "valide": "Validé", "corrige": "Corrigé"
            }.get(resultat["validation"]["statut"], resultat["validation"]["statut"])
            st.session_state.confirmation_validation_nlp = (
                f"Contrôle n° {selection:02d} enregistré : {statut_affiche}. "
                "Il apparaît maintenant dans l'historique."
            )
            st.rerun()
        except ValueError as erreur:
            st.error(str(erreur))


def page_validation_nlp():
    entete()
    st.subheader("Validation humaine")
    onglet_metier, onglet_nlp = st.tabs([
        "Documents métier à vérifier", "Contrôle des entités NLP"
    ])
    with onglet_metier:
        page_validation_metier()
    with onglet_nlp:
        page_validation_nlp_existante()


def _contenu_bulle_chat(texte: str) -> str:
    """Transforme le Markdown simple du moteur en HTML sûr pour les bulles."""
    lignes = []
    for ligne in str(texte).splitlines():
        valeur = html.escape(ligne.strip())
        valeur = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", valeur)
        if valeur.startswith("- "):
            lignes.append(f'<div class="chat-bullet">{valeur[2:]}</div>')
        elif valeur:
            lignes.append(f"<div>{valeur}</div>")
        else:
            lignes.append('<div style="height:.25rem"></div>')
    return "".join(lignes)


def afficher_chatbot_flottant():
    """Affiche un assistant discret, disponible sur toutes les pages."""
    version_chatbot_courante = _empreinte_moteur_chatbot()
    if st.session_state.get("chat_btp_version") != version_chatbot_courante:
        # Streamlit peut conserver une ressource créée avec l'ancienne logique
        # malgré le rechargement à chaud du fichier. On invalide explicitement
        # le moteur afin que les nouvelles règles de pertinence soient actives.
        st.session_state.chat_btp_version = version_chatbot_courante
        st.session_state.chat_btp_messages = [
            {
                "role": "assistant",
                "content": "Bonjour ! Je suis votre assistant documentaire BTP.",
                "sources": [],
                "mode": "accueil",
                "duree": 0.0,
            },
            {
                "role": "assistant",
                "content": (
                    "Posez-moi une question sur un devis, un CCTP, un contrat, "
                    "un rapport ou un guide métier. Mes réponses restent liées aux documents sources."
                ),
                "sources": [],
                "mode": "accueil",
                "duree": 0.0,
            },
        ]

    with st.container(key="chatbot_flottant"):
        with st.popover("Assistant", help="Ouvrir l'assistant documentaire BTP"):
            st.markdown(
                """
                <div class="chat-head">
                  <div class="chat-avatar" aria-hidden="true">
                    <svg viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg">
                      <path d="M32 11v7M28 8a4 4 0 1 0 8 0 4 4 0 1 0-8 0" stroke="white" stroke-width="4" stroke-linecap="round"/>
                      <rect x="12" y="18" width="40" height="34" rx="17" stroke="white" stroke-width="4"/>
                      <circle cx="25" cy="33" r="3" fill="white"/><circle cx="39" cy="33" r="3" fill="white"/>
                      <path d="M24 42c5 4 11 4 16 0M8 29H5m54 0h-3" stroke="white" stroke-width="4" stroke-linecap="round"/>
                    </svg>
                  </div>
                  <div>
                    <div class="chat-title">Assistant BTP</div>
                    <div class="chat-subtitle">Corpus documentaire local</div>
                    <div class="chat-status">En ligne</div>
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            documents_chat = sorted(
                {
                    str(document.get("nom_fichier") or "").strip()
                    for document in charger_documents()
                    if str(document.get("nom_fichier") or "").strip()
                }
            )
            options_documents_chat = ["Tous les documents"] + documents_chat

            def reinitialiser_chat_apres_changement_document():
                """Retire les réponses produites avec l'ancien périmètre documentaire."""
                if "chat_btp_messages" in st.session_state:
                    st.session_state.chat_btp_messages = st.session_state.chat_btp_messages[:2]

            espace_outils, outils_droite = st.columns([7, 1])
            with espace_outils:
                document_selectionne = st.selectbox(
                    "Périmètre documentaire",
                    options_documents_chat,
                    key="chat_btp_document",
                    on_change=reinitialiser_chat_apres_changement_document,
                    help=(
                        "Choisissez un PDF pour limiter la recherche à ce document, "
                        "ou conservez Tous les documents."
                    ),
                    label_visibility="collapsed",
                )
            with outils_droite:
                if st.button("↺", key="chat_btp_effacer", help="Nouvelle conversation"):
                    st.session_state.chat_btp_messages = st.session_state.chat_btp_messages[:2]

            # La conversation défile dans cette zone ; le formulaire reste ainsi
            # toujours visible en bas du panneau, même avec de longues réponses.
            zone_messages = st.container(height=205, border=False)
            with st.form("chat_btp_form", clear_on_submit=True):
                st.markdown("**Posez votre question**")
                colonne_question, colonne_envoi = st.columns([3.25, 1.25])
                with colonne_question:
                    question = st.text_input(
                        "Votre question",
                        placeholder="Votre question sur les documents...",
                        label_visibility="collapsed",
                        key="chat_btp_question",
                    )
                with colonne_envoi:
                    envoyer = st.form_submit_button(
                        "Envoyer", width="stretch", type="primary", icon=":material/send:"
                    )

            if envoyer and question.strip():
                historique = [
                    {"role": message["role"], "content": message["content"]}
                    for message in st.session_state.chat_btp_messages[-6:]
                ]
                st.session_state.chat_btp_messages.append(
                    {"role": "user", "content": question.strip(), "sources": []}
                )
                try:
                    version_question = _empreinte_moteur_chatbot()
                    # Une application Streamlit ouverte pendant une correction peut
                    # conserver une ancienne ressource Python en memoire. Pour une
                    # question documentaire, la fiabilite prime sur ce petit gain de
                    # chargement : on reconstruit donc explicitement le moteur courant.
                    # Les donnees SQLite et les PDF ne sont pas modifies.
                    charger_assistant_btp.clear()
                    assistant = charger_assistant_btp(version_question)
                    with st.spinner("Recherche dans le corpus local..."):
                        # Synchronisation incrémentale : aucun recalcul si le corpus n'a pas changé.
                        assistant.synchroniser()
                        document_cible = (
                            None if document_selectionne == "Tous les documents"
                            else document_selectionne
                        )
                        reponse = assistant.repondre(
                            question, historique, document_cible=document_cible
                        )
                    print(
                        "[CHATBOT] "
                        f"version={version_question} mode={reponse.mode} "
                        f"document={document_cible or 'TOUS'} "
                        f"sources={len(reponse.sources)}"
                    )
                    st.session_state.chat_btp_messages.append(
                        {
                            "role": "assistant",
                            "content": reponse.texte,
                            "sources": [
                                {
                                    "document": source.document,
                                    "page": source.page,
                                    "type_document": source.type_document,
                                    "titre": source.titre,
                                    "texte": source.texte,
                                }
                                for source in reponse.sources
                            ],
                            "mode": reponse.mode,
                            "duree": reponse.duree_secondes,
                            "question": question.strip(),
                            "document_cible": document_cible,
                        }
                    )
                except Exception as erreur:
                    st.session_state.chat_btp_messages.append(
                        {
                            "role": "assistant",
                            "content": f"Je ne peux pas effectuer la recherche locale : {erreur}",
                            "sources": [], "mode": "erreur", "duree": 0.0,
                        }
                    )

            with zone_messages:
                for indice_message, message in enumerate(st.session_state.chat_btp_messages):
                    contenu = _contenu_bulle_chat(message["content"])
                    if message["role"] == "user":
                        st.markdown(
                            f'<div class="chat-row chat-row-user"><div class="chat-bubble '
                            f'chat-bubble-user">{contenu}</div></div>',
                            unsafe_allow_html=True,
                        )
                    else:
                        st.markdown(
                            f"""
                            <div class="chat-row chat-row-assistant">
                              <div class="chat-bot-mini" aria-hidden="true">
                                <svg viewBox="0 0 64 64" fill="none">
                                  <rect x="12" y="18" width="40" height="34" rx="17" stroke="white" stroke-width="4"/>
                                  <circle cx="25" cy="33" r="3" fill="white"/><circle cx="39" cy="33" r="3" fill="white"/>
                                  <path d="M32 11v7M24 42c5 4 11 4 16 0" stroke="white" stroke-width="4" stroke-linecap="round"/>
                                </svg>
                              </div>
                              <div class="chat-bubble chat-bubble-assistant">{contenu}</div>
                            </div>
                            """,
                            unsafe_allow_html=True,
                        )

                        if message.get("duree"):
                            if message.get("feedback"):
                                symbole = "👍" if message["feedback"] == "utile" else "👎"
                                libelle_feedback = (
                                    "Réponse utile" if message["feedback"] == "utile"
                                    else "Réponse à améliorer"
                                )
                                st.markdown(
                                    f'<div class="chat-feedback-note">{symbole} {libelle_feedback}</div>',
                                    unsafe_allow_html=True,
                                )
                            else:
                                marge_avis, avis_utile, avis_ameliorer, espace_avis = st.columns(
                                    [0.42, 0.34, 0.34, 3.15]
                                )
                                with avis_utile:
                                    if st.button(
                                        "👍", key=f"chat_feedback_yes_{indice_message}",
                                        help="Cette réponse est utile",
                                    ):
                                        enregistrer_avis_chatbot(
                                            question=message.get("question", ""),
                                            reponse=message["content"],
                                            verdict="utile",
                                            sources=message.get("sources") or [],
                                            document_cible=message.get("document_cible"),
                                        )
                                        message["feedback"] = "utile"
                                        st.rerun()
                                with avis_ameliorer:
                                    if st.button(
                                        "👎", key=f"chat_feedback_no_{indice_message}",
                                        help="Cette réponse est à améliorer",
                                    ):
                                        enregistrer_avis_chatbot(
                                            question=message.get("question", ""),
                                            reponse=message["content"],
                                            verdict="a_ameliorer",
                                            sources=message.get("sources") or [],
                                            document_cible=message.get("document_cible"),
                                        )
                                        message["feedback"] = "a_ameliorer"
                                        st.rerun()

                    sources = message.get("sources") or []
                    if sources:
                        with st.container(key=f"chat_sources_{id(message)}"):
                            st.markdown(
                                f'<div class="chat-proof-badge">✓ Réponse appuyée par '
                                f'{len(sources)} source(s)</div>',
                                unsafe_allow_html=True,
                            )
                            with st.expander(f"📚 Preuves documentaires · {len(sources)}"):
                                for numero, source in enumerate(sources, 1):
                                    page = source.get("page") or "non précisée"
                                    titre_source = source.get("titre") or source.get("type_document", "")
                                    extrait_source = str(source.get("texte") or "").strip()
                                    st.markdown(
                                        f'<div class="chat-proof-card">'
                                        f'<div class="chat-proof-title">{numero}. '
                                        f'{html.escape(str(source["document"]))} — page {html.escape(str(page))}</div>'
                                        f'<div class="chat-proof-text"><strong>{html.escape(str(titre_source))}</strong>'
                                        f'{" — " if titre_source and extrait_source else ""}'
                                        f'{html.escape(extrait_source)}</div></div>',
                                        unsafe_allow_html=True,
                                    )
@st.cache_resource
def _initialiser_application():
    """Initialise le schéma une seule fois au démarrage du serveur Streamlit."""
    initialiser_base()


def main():
    # Thème visuel isolé : aucune incidence sur le pipeline ou les données.
    inject_command_center_theme()
    _initialiser_application()
    st.sidebar.markdown(
        """
        <div class="side-brand">
          <div class="side-logo">MP</div>
          <div>
            <div class="side-brand-title">Assistant Documents BTP</div>
            <div class="side-brand-subtitle">Ménara Préfa · Analyse intelligente</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if "page_navigation" not in st.session_state:
        st.session_state.page_navigation = "Tableau de bord"

    recherche_page = st.sidebar.text_input(
        "Rechercher une page", placeholder="Rechercher...",
        label_visibility="collapsed", key="recherche_navigation",
    ).casefold().strip()
    groupes_navigation = {
        "Accueil": [("Vue d'ensemble", "Tableau de bord", ":material/home:")],
        "Documents": [
            ("Corpus documentaire", "Documents", ":material/folder_open:"),
            ("Analyser un document", "Nouveau document", ":material/upload_file:"),
            ("Extractions CCTP / DQE", "Extractions", ":material/file_download:"),
        ],
        "Intelligence documentaire": [
            ("Documents métier", "Documents métier", ":material/description:"),
            ("Entités techniques NLP", "Entités NLP", ":material/neurology:"),
            ("Rapprochement CCTP / DQE", "Rapprochement", ":material/compare_arrows:"),
        ],
        "Gouvernance": [
            ("Validation humaine", "Validation NLP", ":material/fact_check:"),
            ("Qualité et métriques", "Qualité & NLP", ":material/monitoring:"),
        ],
    }
    for nom_groupe, liens in groupes_navigation.items():
        liens_visibles = [
            (libelle, destination, icone) for libelle, destination, icone in liens
            if not recherche_page or recherche_page in libelle.casefold()
        ]
        if not liens_visibles:
            continue
        st.sidebar.markdown(f'<div class="side-section">{nom_groupe}</div>', unsafe_allow_html=True)
        for libelle, destination, icone in liens_visibles:
            actif = st.session_state.page_navigation == destination
            if st.sidebar.button(
                libelle, key=f"nav_{destination}", width="stretch",
                type="primary" if actif else "secondary", icon=icone,
            ):
                st.session_state.page_navigation = destination

    page = st.session_state.page_navigation
    if page == "Tableau de bord":
        page_tableau_de_bord()
    elif page == "Documents":
        page_documents()
    elif page == "Nouveau document":
        page_analyser_document()
    elif page == "Extractions":
        page_extractions()
    elif page == "Documents métier":
        page_documents_metier()
    elif page == "Entités NLP":
        page_entites_nlp()
    elif page == "Rapprochement":
        page_rapprochement()
    elif page == "Validation NLP":
        page_validation_nlp()
    else:
        page_qualite_nlp()

    afficher_chatbot_flottant()


if __name__ == "__main__":
    st.markdown(
        """
        <style>
        section[data-testid="stSidebar"],
        [data-testid="stSidebar"] > div:first-child {
            background-color: #F3F4F6 !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    main()
