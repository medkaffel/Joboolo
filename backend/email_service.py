import os
import asyncio
import logging
from urllib.parse import quote

logger = logging.getLogger(__name__)

RESEND_API_KEY = os.environ.get("RESEND_API_KEY")
SENDER_EMAIL = os.environ.get("SENDER_EMAIL", "onboarding@resend.dev")

_resend_ready = False
if RESEND_API_KEY:
    try:
        import resend
        resend.api_key = RESEND_API_KEY
        _resend_ready = True
    except Exception as e:  # pragma: no cover
        logger.warning(f"Resend init failed: {e}")


def _tracked(app_url: str, alert_id: str, target: str) -> str:
    """Wrap a link through the alert click tracker for billing / open-tracking."""
    if not alert_id:
        return target
    return f"{app_url}/api/alerts/track/{alert_id}?redirect={quote(target, safe='')}"


def _job_row(job: dict, app_url: str = "", alert_id: str = None) -> str:
    salary = ""
    if job.get("salary_min") and job.get("salary_max"):
        salary = f"{job['salary_min']:,} - {job['salary_max']:,} € / an".replace(",", " ")
    job_id = job.get("_id") or job.get("id") or ""
    link = _tracked(app_url, alert_id, f"{app_url}/jobs/{job_id}")
    title = job.get('title', '')
    title_html = f'<a href="{link}" style="color:#111827;text-decoration:none;">{title}</a>' if job_id else title
    return f"""
    <tr>
      <td style="padding:16px;border:1px solid #e5e7eb;border-radius:8px;">
        <div style="font-size:16px;font-weight:600;color:#111827;">{title_html}</div>
        <div style="font-size:13px;color:#6b7280;margin-top:4px;">{job.get('location','')} · {job.get('job_type','')}</div>
        {f'<div style="font-size:13px;color:#2563eb;margin-top:4px;">{salary}</div>' if salary else ''}
      </td>
    </tr>
    <tr><td style="height:12px;"></td></tr>
    """


def build_alert_html(alert_name: str, jobs: list, app_url: str, alert_id: str = None) -> str:
    rows = "".join(_job_row(j, app_url, alert_id) for j in jobs)
    manage = f"{app_url}/profile"
    return f"""
    <div style="font-family:Arial,sans-serif;background:#f9fafb;padding:24px;">
      <table width="100%" style="max-width:600px;margin:0 auto;">
        <tr><td>
          <h1 style="color:#2563eb;font-size:24px;">Joboolo</h1>
          <p style="color:#374151;font-size:15px;">
            {len(jobs)} nouvelle(s) offre(s) pour votre alerte « <strong>{alert_name}</strong> » :
          </p>
          <table width="100%">{rows}</table>
          <a href="{_tracked(app_url, alert_id, app_url)}" style="display:inline-block;margin-top:16px;background:#2563eb;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;">
            Voir toutes les offres
          </a>
          <p style="color:#9ca3af;font-size:12px;margin-top:24px;">
            Vous recevez cet email car vous avez créé une alerte sur Joboolo.
            <a href="{manage}" style="color:#6b7280;">Modifier</a> ·
            <a href="{manage}" style="color:#6b7280;">Désactiver l'alerte</a> ·
            <a href="{manage}" style="color:#6b7280;">Se désinscrire</a>
          </p>
        </td></tr>
      </table>
    </div>
    """


STATUS_MESSAGES = {
    "reviewed": ("Votre candidature a été consultée",
                 "Bonne nouvelle : le recruteur a consulté votre candidature. Elle est en cours d'examen."),
    "accepted": ("Votre candidature a été acceptée 🎉",
                 "Félicitations ! Votre candidature a été acceptée. Le recruteur vous contactera prochainement pour la suite."),
    "rejected": ("Réponse concernant votre candidature",
                 "Nous vous remercions pour votre candidature. Malheureusement, elle n'a pas été retenue pour ce poste. Ne perdez pas espoir, de nouvelles offres vous attendent !"),
}


def build_status_email(candidate_name: str, job_title: str, company: str, status: str, app_url: str) -> tuple:
    subject, message = STATUS_MESSAGES.get(status, ("Mise à jour de votre candidature", "Le statut de votre candidature a été mis à jour."))
    accent = "#16a34a" if status == "accepted" else ("#dc2626" if status == "rejected" else "#2563eb")
    html = f"""
    <div style="font-family:Arial,sans-serif;background:#f9fafb;padding:24px;">
      <table width="100%" style="max-width:600px;margin:0 auto;">
        <tr><td>
          <h1 style="color:#2563eb;font-size:24px;">Joboolo</h1>
          <p style="color:#374151;font-size:15px;">Bonjour {candidate_name},</p>
          <div style="border-left:4px solid {accent};padding:12px 16px;background:#fff;border-radius:6px;margin:16px 0;">
            <p style="color:#111827;font-size:16px;margin:0 0 6px;">{message}</p>
            <p style="color:#6b7280;font-size:14px;margin:0;">Poste : <strong>{job_title}</strong> — {company}</p>
          </div>
          <a href="{app_url}/my-applications" style="display:inline-block;margin-top:8px;background:{accent};color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;">
            Voir mes candidatures
          </a>
          <p style="color:#9ca3af;font-size:12px;margin-top:24px;">Email envoyé automatiquement par Joboolo.</p>
        </td></tr>
      </table>
    </div>
    """
    return subject, html


def build_application_confirmation_email(candidate_name: str, job_title: str, company: str, app_url: str) -> tuple:
    subject = f"Candidature envoyée — {job_title}"
    html = f"""
    <div style="font-family:Arial,sans-serif;background:#f9fafb;padding:24px;">
      <table width="100%" style="max-width:600px;margin:0 auto;">
        <tr><td>
          <h1 style="color:#2563eb;font-size:24px;">Joboolo</h1>
          <p style="color:#374151;font-size:15px;">Bonjour {candidate_name},</p>
          <div style="border-left:4px solid #2563eb;padding:12px 16px;background:#fff;border-radius:6px;margin:16px 0;">
            <p style="color:#111827;font-size:16px;margin:0 0 6px;">Votre candidature a bien été envoyée ✅</p>
            <p style="color:#6b7280;font-size:14px;margin:0;">Poste : <strong>{job_title}</strong> — {company}</p>
          </div>
          <p style="color:#374151;font-size:14px;">Le recruteur va étudier votre profil. Vous serez notifié(e) par email dès que le statut évolue.</p>
          <a href="{app_url}/my-applications" style="display:inline-block;margin-top:8px;background:#2563eb;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;">
            Suivre mes candidatures
          </a>
          <p style="color:#9ca3af;font-size:12px;margin-top:24px;">Email envoyé automatiquement par Joboolo.</p>
        </td></tr>
      </table>
    </div>
    """
    return subject, html


def build_new_application_email(employer_name: str, candidate_name: str, job_title: str, job_id: str, app_url: str) -> tuple:
    subject = f"Nouvelle candidature — {job_title}"
    html = f"""
    <div style="font-family:Arial,sans-serif;background:#f9fafb;padding:24px;">
      <table width="100%" style="max-width:600px;margin:0 auto;">
        <tr><td>
          <h1 style="color:#2563eb;font-size:24px;">Joboolo</h1>
          <p style="color:#374151;font-size:15px;">Bonjour {employer_name},</p>
          <div style="border-left:4px solid #16a34a;padding:12px 16px;background:#fff;border-radius:6px;margin:16px 0;">
            <p style="color:#111827;font-size:16px;margin:0 0 6px;"><strong>{candidate_name}</strong> a postulé à votre offre 🎯</p>
            <p style="color:#6b7280;font-size:14px;margin:0;">Poste : <strong>{job_title}</strong></p>
          </div>
          <a href="{app_url}/my-jobs/{job_id}/applications" style="display:inline-block;margin-top:8px;background:#2563eb;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;">
            Voir la candidature
          </a>
          <p style="color:#9ca3af;font-size:12px;margin-top:24px;">Email envoyé automatiquement par Joboolo.</p>
        </td></tr>
      </table>
    </div>
    """
    return subject, html


def build_low_balance_email(company_name: str, balance: float, threshold: float, app_url: str) -> tuple:
    subject = "⚠️ Solde bas — rechargez votre compte Joboolo"
    html = f"""
    <div style="font-family:Arial,sans-serif;background:#f9fafb;padding:24px;">
      <table width="100%" style="max-width:600px;margin:0 auto;">
        <tr><td>
          <h1 style="color:#2563eb;font-size:24px;">Joboolo</h1>
          <p style="color:#374151;font-size:15px;">Bonjour {company_name},</p>
          <div style="border-left:4px solid #f59e0b;padding:12px 16px;background:#fff;border-radius:6px;margin:16px 0;">
            <p style="color:#111827;font-size:16px;margin:0 0 6px;">Votre solde est bas ⚠️</p>
            <p style="color:#6b7280;font-size:14px;margin:0;">Solde actuel : <strong>{balance:.2f} €</strong> (seuil d'alerte : {threshold:.0f} €).</p>
            <p style="color:#6b7280;font-size:14px;margin:6px 0 0;">Pour éviter toute interruption de diffusion de vos offres, rechargez dès maintenant.</p>
          </div>
          <a href="{app_url}/partenaire" style="display:inline-block;margin-top:8px;background:#2563eb;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;">
            Recharger mon solde
          </a>
          <p style="color:#9ca3af;font-size:12px;margin-top:24px;">Alerte automatique envoyée par Joboolo.</p>
        </td></tr>
      </table>
    </div>
    """
    return subject, html


def build_topup_receipt_email(company_name: str, amount: float, currency: str, new_balance: float, kind: str, app_url: str) -> tuple:
    is_posting = kind == "posting_pack"
    subject = "Reçu de recharge — Joboolo Partenaire"
    detail = (f"<strong>{int(amount)} annonce(s)</strong> ajoutée(s) à votre compte"
              if is_posting else f"Montant crédité : <strong>{amount:.2f} {currency.upper()}</strong>")
    balance_line = (f"Annonces restantes : <strong>{int(new_balance)}</strong>"
                    if is_posting else f"Nouveau solde : <strong>{new_balance:.2f} {currency.upper()}</strong>")
    html = f"""
    <div style="font-family:Arial,sans-serif;background:#f9fafb;padding:24px;">
      <table width="100%" style="max-width:600px;margin:0 auto;">
        <tr><td>
          <h1 style="color:#2563eb;font-size:24px;">Joboolo</h1>
          <p style="color:#374151;font-size:15px;">Bonjour {company_name},</p>
          <div style="border-left:4px solid #16a34a;padding:12px 16px;background:#fff;border-radius:6px;margin:16px 0;">
            <p style="color:#111827;font-size:16px;margin:0 0 6px;">Votre recharge a été confirmée ✅</p>
            <p style="color:#6b7280;font-size:14px;margin:0 0 4px;">{detail}</p>
            <p style="color:#6b7280;font-size:14px;margin:0;">{balance_line}</p>
          </div>
          <a href="{app_url}/partenaire" style="display:inline-block;margin-top:8px;background:#2563eb;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;">
            Accéder à mon espace
          </a>
          <p style="color:#9ca3af;font-size:12px;margin-top:24px;">Reçu envoyé automatiquement par Joboolo.</p>
        </td></tr>
      </table>
    </div>
    """
    return subject, html


def build_new_partner_email(company_name: str, email: str, app_url: str) -> tuple:
    subject = f"🆕 Nouveau partenaire à valider — {company_name}"
    html = f"""
    <div style="font-family:Arial,sans-serif;background:#f9fafb;padding:24px;">
      <table width="100%" style="max-width:600px;margin:0 auto;">
        <tr><td>
          <h1 style="color:#2563eb;font-size:24px;">Joboolo</h1>
          <p style="color:#374151;font-size:15px;">Un nouveau partenaire vient de s'inscrire et attend votre validation.</p>
          <div style="border-left:4px solid #2563eb;padding:12px 16px;background:#fff;border-radius:6px;margin:16px 0;">
            <p style="color:#111827;font-size:16px;margin:0 0 6px;">Société : <strong>{company_name}</strong></p>
            <p style="color:#6b7280;font-size:14px;margin:0;">Email : {email}</p>
          </div>
          <a href="{app_url}/adminos" style="display:inline-block;margin-top:8px;background:#2563eb;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;">
            Valider le partenaire
          </a>
          <p style="color:#9ca3af;font-size:12px;margin-top:24px;">Activez le compte depuis l'onglet Partenaires du back-office.</p>
        </td></tr>
      </table>
    </div>
    """
    return subject, html


def build_auto_import_email(company_name: str, campaign_name: str, imported: int, updated: int, app_url: str) -> tuple:
    subject = f"📥 Import automatique — {campaign_name} : {imported} nouvelle(s), {updated} mise(s) à jour"
    html = f"""
    <div style="font-family:Arial,sans-serif;background:#f9fafb;padding:24px;">
      <table width="100%" style="max-width:600px;margin:0 auto;">
        <tr><td>
          <h1 style="color:#2563eb;font-size:24px;">Joboolo</h1>
          <p style="color:#374151;font-size:15px;">Bonjour {company_name},</p>
          <p style="color:#374151;font-size:15px;">L'import automatique de votre campagne <strong>{campaign_name}</strong> vient de s'exécuter.</p>
          <div style="display:flex;gap:12px;margin:16px 0;">
            <div style="flex:1;background:#eff6ff;border-radius:10px;padding:16px;text-align:center;">
              <div style="font-size:28px;font-weight:800;color:#2563eb;">{imported}</div>
              <div style="font-size:13px;color:#6b7280;">Nouvelles annonces</div>
            </div>
            <div style="flex:1;background:#f0fdf4;border-radius:10px;padding:16px;text-align:center;">
              <div style="font-size:28px;font-weight:800;color:#16a34a;">{updated}</div>
              <div style="font-size:13px;color:#6b7280;">Annonces mises à jour</div>
            </div>
          </div>
          <a href="{app_url}/partenaire" style="display:inline-block;margin-top:8px;background:#2563eb;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;">
            Voir mon tableau de bord
          </a>
          <p style="color:#9ca3af;font-size:12px;margin-top:24px;">Vous recevez cet email car l'import automatique est activé pour vos campagnes.</p>
        </td></tr>
      </table>
    </div>
    """
    return subject, html


def build_partner_welcome_email(company_name: str, app_url: str) -> tuple:
    subject = "🎉 Bienvenue sur Joboolo — votre compte partenaire est activé"
    html = f"""
    <div style="font-family:Arial,sans-serif;background:#f9fafb;padding:24px;">
      <table width="100%" style="max-width:600px;margin:0 auto;">
        <tr><td>
          <h1 style="color:#2563eb;font-size:24px;">Joboolo</h1>
          <p style="color:#374151;font-size:15px;">Bonjour {company_name},</p>
          <p style="color:#374151;font-size:15px;">Bonne nouvelle : votre compte partenaire vient d'être <strong>validé et activé</strong> par notre équipe. Vous pouvez dès maintenant vous connecter, créer vos campagnes de diffusion et configurer vos flux XML.</p>
          <ul style="color:#374151;font-size:14px;line-height:1.7;">
            <li>Créez une campagne et branchez votre flux XML</li>
            <li>Choisissez votre mode de facturation (au clic ou par pack)</li>
            <li>Suivez vos performances (impressions, clics, CTR)</li>
          </ul>
          <a href="{app_url}/partenaire" style="display:inline-block;margin-top:8px;background:#2563eb;color:#fff;padding:12px 24px;border-radius:8px;text-decoration:none;">
            Accéder à mon espace partenaire
          </a>
          <p style="color:#9ca3af;font-size:12px;margin-top:24px;">Besoin d'aide ? Répondez simplement à cet email.</p>
        </td></tr>
      </table>
    </div>
    """
    return subject, html


async def send_alert_email(recipient_email: str, subject: str, html_content: str) -> bool:
    if not _resend_ready:
        logger.info(f"[email disabled] Would send to {recipient_email}: {subject}")
        return False

    import resend
    params = {
        "from": SENDER_EMAIL,
        "to": [recipient_email],
        "subject": subject,
        "html": html_content,
    }
    try:
        await asyncio.to_thread(resend.Emails.send, params)
        logger.info(f"Alert email sent to {recipient_email}")
        return True
    except Exception as e:
        logger.error(f"Failed to send alert email: {e}")
        return False
