# voh_app/route.py

from flask import Flask, render_template, request, redirect, url_for, flash, abort
import psycopg2  # type: ignore
import psycopg2.extras  # type: ignore
import psycopg2.errors  # type: ignore
from datetime import datetime
from config import Config
from flask import Blueprint
import secrets

# =====================================================
# INITIALISATION DE L'APPLICATION
# =====================================================

voh_bp = Blueprint('voh', __name__, template_folder='templates')

# =====================================================
# CONNEXION À LA BASE DE DONNÉES
# =====================================================

def get_db_connection():
    """Connexion à PostgreSQL"""
    try:
        conn = psycopg2.connect(
            host=Config.DB_HOST,
            port=Config.DB_PORT,
            database=Config.DB_DATABASE,
            user=Config.DB_LOGIN,
            password=Config.DB_PASSWORD,
            sslmode=Config.SSL_MODE
        )
        return conn
    except Exception as e:
        raise e

# =====================================================
# IDS COURTS & LISIBLE (préfixés par l'année)
# =====================================================

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # lisible: pas de 0/O/I/l

def current_year() -> int:
    return datetime.now().year

def year_prefix(year: int) -> str:
    """Ex: 2025 -> '25-'"""
    return f"{str(year)[-2:]}-"

def new_id_year_prefixed(year: int, core_len: int = 8) -> str:
    """ID lisible et court, préfixé par l'année. Ex: '25-8FK2Z91P'"""
    core = "".join(secrets.choice(ALPHABET) for _ in range(core_len))
    return f"{year_prefix(year)}{core}"

def current_prev_week_label() -> str:
    """Retourne 'Wn' pour la semaine ISO précédente (ex: W42)."""
    iso_week = datetime.now().isocalendar()[1]
    prev_week = iso_week - 1 if iso_week > 1 else 1
    return f"W{prev_week}"

# =====================================================
# FONCTION UTILITAIRE POUR UPDATE
# =====================================================

def parse_form_data(form):
    """Prépare les données pour l’update sans modifier import_date ni year."""
    return {
        'id': form['id'],
        'bu': form['bu'],
        'department_function': form['department_function'],
        'dl_headcount': int(form['dl_headcount']),
        'type': form['type'],
        'h100': float(form['h100']),
        'h125': float(form['h125']) * 1.25,
        'h150': float(form['h150']) * 0.5,
        'h200': float(form['h200']) * 2,
        'weekno': form['weekno']
    }

# =====================================================
# INSERT AVEC RETRY SUR COLLISION D'ID
# =====================================================

INSERT_SQL = """
    INSERT INTO public.weekly_voh_metrics
    ("ID","BU","Department_function","Type","DL_Headcount",
     "H100","H125","H150","H200","WeekNo","Import_Date","Year")
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    ON CONFLICT ("ID") DO NOTHING
    RETURNING "ID"
"""

def insert_with_short_id(cur, year: int, values_builder, max_tries: int = 5):
    """
    Tente d'insérer avec un ID court préfixé par l'année (ex: '25-XXXXXXX').
    - Si conflit uniquement sur "ID": on regénère et on réessaie (ON CONFLICT DO NOTHING).
    - Toute autre contrainte (ex: métier) remonte via psycopg2.errors.UniqueViolation.
    """
    for _ in range(max_tries):
        rid = new_id_year_prefixed(year)  # core 8 par défaut
        values = values_builder(rid)
        cur.execute(INSERT_SQL, values)
        row = cur.fetchone()  # None si DO NOTHING (collision d'ID), sinon l'ID inséré
        if row is not None:
            return rid
    raise RuntimeError("Impossible de générer un ID court unique après plusieurs tentatives.")

# =====================================================
# ROUTE PRINCIPALE (INSERT + SELECT)
# =====================================================

@voh_bp.route('/', methods=['GET', 'POST'])
def index():
    conn = None
    metrics = []
    column_names = [
        "ID", "BU", "Department_function", "DL_Headcount",
        "H100", "H125", "H150", "H200", "WeekNo", "Import_Date", "Year"
    ]
    filled_week = None  # pour la bannière d'info

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        if request.method == 'POST':
            try:
                # Dictionnaire des types selon les lignes
                TYPE_MAP = {
                    "SUPERVISOR VALEO": "VOH", "AQC VALEO": "VOH", "REG VALEO": "VOH", "SPC VALEO": "VOH",
                    "TRAINER VALEO": "ADMIN", "METHODS VALEO": "FOH", "TEAM LEADER VALEO": "FOH", "CSL VALEO": "VOH",
                    "SUPERVISOR NIDEC": "VOH", "AQC NIDEC": "VOH", "REG NIDEC": "VOH", "SPC NIDEC": "VOH",
                    "TRAINER NIDEC": "ADMIN", "METHODS NIDEC": "FOH", "TEAM LEADER NIDEC": "FOH", "CSL NIDEC": "VOH",
                    "MAINTENANCE": "VOH", "AQF": "VOH", "WAREHOUSE": "VOH", "SCRAP": "VOH",
                    "QUALITY": "FOH", "LOGISTICS": "FOH", "FINANCE": "ADMIN", "INDUS/CIP": "FOH",
                    "HR": "ADMIN", "PURCHASING": "ADMIN", "EXECUTIVE ASSISTANT": "ADMIN", "IT": "ADMIN", "PROJECT": "FOH"
                }

                lines_valeo = [
                    "SUPERVISOR VALEO", "AQC VALEO", "REG VALEO", "SPC VALEO",
                    "TRAINER VALEO", "METHODS VALEO", "TEAM LEADER VALEO", "CSL VALEO"
                ]
                lines_nidec = [
                    "SUPERVISOR NIDEC", "AQC NIDEC", "REG NIDEC", "SPC NIDEC",
                    "TRAINER NIDEC", "METHODS NIDEC", "TEAM LEADER NIDEC", "CSL NIDEC"
                ]
                lines_other = [
                    "MAINTENANCE", "AQF", "WAREHOUSE", "SCRAP", "QUALITY", "LOGISTICS",
                    "FINANCE", "INDUS/CIP", "HR", "PURCHASING", "EXECUTIVE ASSISTANT", "IT", "PROJECT"
                ]

                weekno = request.form['weekno']
                import_date = datetime.now().date()
                year = current_year()

                # === Fonction générique d’insertion (ID court auto-généré) ===
                def insert_lines(bu, lines):
                    for line in lines:
                        dl_headcount = int(request.form.get(f"{line}_dl_headcount", 0) or 0)
                        h100 = float(request.form.get(f"{line}_h100", 0) or 0)
                        h125 = float(request.form.get(f"{line}_h125", 0) or 0) * 1.25
                        h150 = float(request.form.get(f"{line}_h150", 0) or 0) * 0.5
                        h200 = float(request.form.get(f"{line}_h200", 0) or 0) * 2
                        type_value = TYPE_MAP.get(line, "VOH")

                        def values_builder(rid):
                            return (
                                rid, bu, line, type_value, dl_headcount,
                                h100, h125, h150, h200, weekno, import_date, year
                            )

                        insert_with_short_id(cur, year, values_builder)

                # Insertion pour chaque BU
                insert_lines("VALEO", lines_valeo)
                insert_lines("NIDEC", lines_nidec)
                insert_lines("OTHER", lines_other)

                conn.commit()
                flash("✅ Toutes les lignes ont été enregistrées avec succès !", "success")
                # NEW: rediriger avec ?filled_week=Wnn
                return redirect(url_for('voh.index', filled_week=weekno))

            except psycopg2.errors.UniqueViolation:
                if conn: conn.rollback()
                # Probable contrainte métier (ex: BU+fonction+semaine+année)
                flash(f"⚠️ Erreur : Des données existent déjà pour la semaine {weekno}. Veuillez modifier les données existantes.", 'warning')
            except ValueError as ve:
                if conn: conn.rollback()
                flash(f"❌ Erreur de saisie : Veuillez vérifier que tous les champs numériques sont corrects. Détails : {ve}", 'danger')
            except RuntimeError as rid_err:
                if conn: conn.rollback()
                flash(f"❌ Erreur lors de la génération d'ID : {rid_err}", 'danger')
            except psycopg2.Error as db_error:
                if conn: conn.rollback()
                flash(f"❌ Erreur de base de données : {db_error}", 'danger')

        # Sélection de toutes les données existantes
        select_query = """
            SELECT "ID", "BU", "Department_function", "DL_Headcount",
                   "H100",
                   COALESCE("H125",0) / 1.25 as "H125",
                   COALESCE("H150",0) / 0.5 as "H150",
                   COALESCE("H200",0) / 2 as "H200",
                   "WeekNo", "Import_Date", "Year"
            FROM public.weekly_voh_metrics
            ORDER BY "Import_Date" DESC, "WeekNo" DESC
        """
        cur.execute(select_query)
        metrics = cur.fetchall()

        # NEW: compute banner week for normal visits if previous week exists
        filled_week = request.args.get('filled_week')  # post-submit behavior
        if not filled_week:
            default_week = current_prev_week_label()
            cur.execute(
                'SELECT 1 FROM public.weekly_voh_metrics WHERE "Year" = %s AND "WeekNo" = %s LIMIT 1',
                (current_year(), default_week)
            )
            if cur.fetchone():
                filled_week = default_week

    except Exception as e:
        if conn:
            conn.rollback()
        flash(f"❌ Erreur système : {e}", 'danger')
        return redirect(url_for('voh.index'))

    finally:
        if conn:
            conn.close()

    # NEW: pass filled_week to template for the info banner
    return render_template(
        'voh/index.html',
        metrics=metrics,
        column_names=column_names,
        datetime=datetime,
        filled_week=filled_week
    )

# =====================================================
# ROUTE DE MISE À JOUR
# =====================================================

@voh_bp.route('/update/<string:id>', methods=['GET', 'POST'])
def update(id):
    conn = None
    metric = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        if request.method == 'POST':
            data = parse_form_data(request.form)

            update_query = """
                UPDATE public.weekly_voh_metrics SET
                "BU"=%s, "Department_function"=%s, "Type"=%s, "DL_Headcount"=%s,
                "H100"=%s, "H125"=%s, "H150"=%s, "H200"=%s,
                "WeekNo"=%s
                WHERE "ID" = %s
            """
            values = (
                data['bu'], data['department_function'], data['type'], data['dl_headcount'],
                data['h100'], data['h125'], data['h150'], data['h200'],
                data['weekno'], id
            )
            cur.execute(update_query, values)
            conn.commit()
            flash('✅ Métrique mise à jour avec succès !', 'success')
            return redirect(url_for('voh.index'))

        # Récupération pour affichage du formulaire
        cur.execute("""
          SELECT 
                "ID",
                "BU",
                "Department_function",
                "Type",
                "DL_Headcount",
                "H100",
                ROUND(CAST(COALESCE("H125", 0.00) / 1.25 AS numeric), 2) AS "H125",
                ROUND(CAST(COALESCE("H150", 0.00) / 0.5 AS numeric), 2) AS "H150",
                ROUND(CAST(COALESCE("H200", 0.00) / 2 AS numeric), 2) AS "H200",
                "WeekNo",
                "Import_Date",
                "Year"
          FROM public.weekly_voh_metrics
          WHERE "ID" = %s
        """, (id,))

        metric = cur.fetchone()

        if metric is None:
            abort(404)

    except (ValueError, psycopg2.Error) as e:
        if conn: conn.rollback()
        flash(f"Erreur lors de la modification : {e}", 'danger')
        return render_template('voh/update.html', metric=metric)
    finally:
        if conn: conn.close()

    return render_template('voh/update.html', metric=metric)
