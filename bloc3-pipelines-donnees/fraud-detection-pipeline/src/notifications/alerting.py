"""
Notifications : alertes fraude en temps réel + rapport quotidien.
Si SMTP est configuré, on envoie par email. Sinon on log.
"""
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
from config.settings import SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, ALERT_RECIPIENTS

logger = logging.getLogger(__name__)


def send_fraud_alert(transaction):
    """Alerte quand on détecte une fraude."""
    msg = (
        f"FRAUDE DETECTEE\n"
        f"---\n"
        f"Transaction : {transaction.get('trans_num', 'N/A')}\n"
        f"Montant     : {transaction.get('amt', 'N/A')}\n"
        f"Carte       : ***{str(transaction.get('cc_num', ''))[-4:]}\n"
        f"Commercant  : {transaction.get('merchant', 'N/A')}\n"
        f"Catégorie   : {transaction.get('category', 'N/A')}\n"
        f"Lieu        : {transaction.get('city', '')}, {transaction.get('state', '')}\n"
        f"Probabilité : {transaction.get('fraud_probability', 'N/A')}\n"
        f"Date        : {transaction.get('trans_date_trans_time', 'N/A')}\n"
        f"---"
    )

    logger.warning(msg)

    if SMTP_USER and SMTP_PASSWORD:
        _send_email(
            subject=f"ALERTE FRAUDE - {transaction.get('trans_num', '')}",
            body=msg,
            recipients=ALERT_RECIPIENTS,
        )


def send_daily_report(summary, frauds_detail, top_categories):
    """
    Génère et envoie le rapport quotidien.
    Format HTML pour que ce soit lisible par email.
    """
    report_date = datetime.now().strftime("%Y-%m-%d")

    html = f"""
    <html>
    <head><style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        h1 {{ color: #1A1F36; }}
        h2 {{ color: #0284C7; }}
        table {{ border-collapse: collapse; width: 100%; margin: 15px 0; }}
        th {{ background-color: #1A1F36; color: white; padding: 10px; text-align: left; }}
        td {{ border: 1px solid #ddd; padding: 8px; }}
        tr:nth-child(even) {{ background-color: #f2f2f2; }}
        .fraud {{ color: #EF4444; font-weight: bold; }}
        .stat {{ font-size: 24px; font-weight: bold; color: #0284C7; }}
    </style></head>
    <body>
    <h1>Rapport Quotidien - Fraud Detection</h1>
    <p>Date : {report_date}</p>

    <h2>Résumé</h2>
    <table>
        <tr><th>Métrique</th><th>Valeur</th></tr>
        <tr><td>Total transactions</td><td class="stat">{summary.get('total_transactions', 0)}</td></tr>
        <tr><td>Fraudes détectées</td><td class="fraud">{summary.get('total_frauds', 0)}</td></tr>
        <tr><td>Taux de fraude</td><td>{summary.get('fraud_rate_pct', 0)}%</td></tr>
        <tr><td>Montant total</td><td>{summary.get('total_amount', 0)}</td></tr>
        <tr><td>Montant frauduleux</td><td class="fraud">{summary.get('fraud_amount', 0)}</td></tr>
    </table>

    <h2>Top Catégories</h2>
    <table>
        <tr><th>Catégorie</th><th>Nb Fraudes</th><th>Montant Moyen</th></tr>
    """
    for cat in top_categories:
        html += f"<tr><td>{cat.get('category', '')}</td>"
        html += f"<td>{cat.get('fraud_count', 0)}</td>"
        html += f"<td>{cat.get('avg_fraud_amount', 0)}</td></tr>"

    html += """
    </table>
    <h2>Détail des Fraudes</h2>
    <table>
        <tr><th>Heure</th><th>Carte</th><th>Commercant</th><th>Montant</th><th>Proba</th></tr>
    """
    for f in frauds_detail[:20]:
        html += f"<tr>"
        html += f"<td>{f.get('trans_date_trans_time', '')}</td>"
        html += f"<td>***{str(f.get('cc_num', ''))[-4:]}</td>"
        html += f"<td>{f.get('merchant', '')}</td>"
        html += f"<td class='fraud'>{f.get('amt', '')}</td>"
        html += f"<td>{f.get('fraud_probability', '')}</td></tr>"

    html += "</table></body></html>"

    logger.info(f"Rapport généré pour {report_date}")

    if SMTP_USER and SMTP_PASSWORD:
        _send_email(
            subject=f"Rapport Fraude - {report_date}",
            body=html,
            recipients=ALERT_RECIPIENTS,
            is_html=True,
        )
    else:
        # Pas de SMTP, on sauvegarde en local dans un dossier accessible
        import os as _os
        reports_dir = "/opt/airflow/data/reports"
        _os.makedirs(reports_dir, exist_ok=True)
        path = f"{reports_dir}/fraud_report_{report_date}.html"
        with open(path, "w") as f:
            f.write(html)
        logger.info(f"SMTP non configure, rapport sauve dans {path}")


def _send_email(subject, body, recipients, is_html=False):
    """Envoie un email via SMTP."""
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = SMTP_USER
        msg["To"] = ", ".join(recipients)
        msg.attach(MIMEText(body, "html" if is_html else "plain"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_USER, recipients, msg.as_string())
        logger.info(f"Email envoyé à {recipients}")
    except Exception as e:
        logger.error(f"Erreur envoi email: {e}")
