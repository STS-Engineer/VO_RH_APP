# rh_app/route.py

from flask import Flask, render_template, request, redirect, url_for, flash, abort
import psycopg2  # type: ignore
import psycopg2.extras  # type: ignore
import psycopg2.errors  # type: ignore
from datetime import datetime
from config import Config
from flask import Blueprint
import secrets

# -----------------------------------------------------------------------------
# Flask blueprint
# -----------------------------------------------------------------------------
rh_bp = Blueprint('rh', __name__, template_folder='templates')

# -----------------------------------------------------------------------------
# DB connection
# -----------------------------------------------------------------------------
def get_db_connection():
    """Établit la connexion à PostgreSQL en utilisant les paramètres de config.py."""
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

# -----------------------------------------------------------------------------
# Utils
# -----------------------------------------------------------------------------
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # lisible: pas de 0/O/I/l

def current_year() -> int:
    return datetime.now().year

def year_prefix(year: int) -> str:
    """Retourne un préfixe année sur 2 chiffres + tiret, ex: 2025 -> '25-'"""
    return f"{str(year)[-2:]}-"

def new_id_year_prefixed(year: int, core_len: int = 8) -> str:
    """
    Génère un identifiant lisible, court et préfixé par l'année (2 chiffres).
    Exemple: '25-8FK2Z91P'
    """
    core = "".join(secrets.choice(ALPHABET) for _ in range(core_len))
    return f"{year_prefix(year)}{core}"

def current_prev_week_label() -> str:
    """Retourne 'Wn' pour la semaine ISO précédente (ex: W42)."""
    iso_week = datetime.now().isocalendar()[1]
    prev_week = iso_week - 1 if iso_week > 1 else 1
    return f"W{prev_week}"

def parse_form_data(form):
    """Extrait et convertit les données du formulaire pour l'UPDATE (sans modifier import_date ni year)."""
    return {
        'id': form['id'],
        'bu': form['bu'],
        'production_line': form['production_line'],
        'dl_headcount': int(form['dl_headcount']),
        'h100': float(form['h100']),
        'h125': float(form['h125']) * 1.25,
        'h150': float(form['h150']) * 0.5,
        'h200': float(form['h200']) * 2,
        'weekno': form['weekno']
    }

# Helper d’insertion: réessaie si l’ID (uniquement) est en conflit
# Nécessite un index UNIQUE sur "ID"
INSERT_SQL = """
    INSERT INTO weekly_dl_metrics
    ("ID","BU","Production_line","DL_Headcount","H100","H125","H150","H200","WeekNo","Import_Date","Year")
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    ON CONFLICT ("ID") DO NOTHING
    RETURNING "ID"
"""

def insert_with_short_id(cur, year: int, values_builder, max_tries: int = 5):
    """
    Tente d'insérer avec un ID court préfixé par l'année (ex: '25-XXXXXXX').
    - Si conflit sur "ID": on regénère un ID et on réessaie (ON CONFLICT DO NOTHING).
    - Tout autre conflit (ex: contrainte métier BU+ligne+semaine+année) remonte normalement.
    """
    for _ in range(max_tries):
        rid = new_id_year_prefixed(year)  # core par défaut: 8 caractères
        values = values_builder(rid)
        cur.execute(INSERT_SQL, values)
        row = cur.fetchone()  # None si DO NOTHING (collision d'ID), sinon renvoie l'ID inséré
        if row is not None:
            return rid
    raise RuntimeError("Impossible de générer un ID court unique après plusieurs tentatives.")

# -----------------------------------------------------------------------------
# Routes : INDEX (INSERT, SELECT)
# -----------------------------------------------------------------------------
@rh_bp.route('/', methods=['GET', 'POST'])
def index():
    conn = None
    metrics = []
    colnames = ["ID", "BU", "Production_line", "DL_Headcount", "H100", "H125", "H150", "H200", "WeekNo", "Import_Date", "Year"]
    this_year = current_year()
    banner_week = None  # sera passé au template comme 'filled_week'

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        if request.method == 'POST':
            try:
                # ✅ Lignes fixes Valeo et Nidec
                lines_valeo = ["FLEX", "MNG2", "FP", "GENII R", "GENII C", "BUA", "VM4"]
                lines_nidec = ["NEM2", "SIM AS", "SKP42", "NGMAP", "POWERTOOLS", "10T", "11TA", "DCK", "CM3", "CM4", "FAIX"]

                weekno = request.form['weekno']
                import_date = datetime.now().date()   # ✅ automatique à la saisie
                year = this_year                      # ✅ forcer l'année courante

                # === Valeo ===
                for line in lines_valeo:
                    dl_headcount = int(request.form.get(f"{line}_dl_headcount", 0) or 0)
                    h100 = float(request.form.get(f"{line}_h100", 0) or 0)
                    h125 = float(request.form.get(f"{line}_h125", 0) or 0) * 1.25
                    h150 = float(request.form.get(f"{line}_h150", 0) or 0) * 0.5
                    h200 = float(request.form.get(f"{line}_h200", 0) or 0) * 2

                    def values_builder(rid):
                        return (rid, "VALEO", line, dl_headcount, h100, h125, h150, h200, weekno, import_date, year)

                    insert_with_short_id(cur, year, values_builder)

                # === Nidec ===
                for line in lines_nidec:
                    dl_headcount = int(request.form.get(f"{line}_dl_headcount", 0) or 0)
                    h100 = float(request.form.get(f"{line}_h100", 0) or 0)
                    h125 = float(request.form.get(f"{line}_h125", 0) or 0) * 1.25
                    h150 = float(request.form.get(f"{line}_h150", 0) or 0) * 0.5
                    h200 = float(request.form.get(f"{line}_h200", 0) or 0) * 2

                    def values_builder(rid):
                        return (rid, "NIDEC", line, dl_headcount, h100, h125, h150, h200, weekno, import_date, year)

                    insert_with_short_id(cur, year, values_builder)

                conn.commit()
                flash(f"Toutes les lignes Valeo + Nidec {year} ont été enregistrées avec succès !", "success")
                # redirect avec ?filled_week=...
                return redirect(url_for('rh.index', filled_week=weekno))

            except psycopg2.errors.UniqueViolation:
                # ⚠️ Probable contrainte unique métier (ex: BU+ligne+semaine+année).
                if conn: conn.rollback()
                flash(f"⚠️ Erreur : Des données existent déjà pour la semaine {weekno} de {this_year}. Veuillez modifier les données existantes si besoin.", 'warning')
            except ValueError as ve:
                if conn: conn.rollback()
                flash(f"❌ Erreur de saisie : Veuillez vérifier que tous les champs numériques sont corrects. Détails : {ve}", 'danger')
            except RuntimeError as rid_err:
                if conn: conn.rollback()
                flash(f"❌ Erreur lors de la génération d'ID : {rid_err}", 'danger')
            except psycopg2.Error as db_error:
                if conn: conn.rollback()
                flash(f"❌ Erreur de base de données : {db_error}", 'danger')

        # ✅ Récupération des données existantes de l'année courante uniquement
        select_query = """
        SELECT "ID", "BU", "Production_line", "DL_Headcount",
               "H100",
               COALESCE("H125",0) / 1.25 as "H125",
               COALESCE("H150",0) / 0.5  as "H150",
               COALESCE("H200",0) / 2    as "H200",
               "WeekNo", "Import_Date", "Year"
        FROM weekly_dl_metrics
        WHERE "Year" = %s
        ORDER BY "Import_Date" DESC, "WeekNo" DESC
        """
        cur.execute(select_query, (this_year,))
        metrics = cur.fetchall()

        # --- NEW: compute banner_week for normal visits ---
        banner_week = request.args.get('filled_week')  # garde le comportement post-submit
        if not banner_week:
            default_week = current_prev_week_label()
            cur.execute(
                'SELECT 1 FROM weekly_dl_metrics WHERE "Year" = %s AND "WeekNo" = %s LIMIT 1',
                (this_year, default_week)
            )
            if cur.fetchone():
                banner_week = default_week
        # ---------------------------------------------------

    except Exception as e:
        if conn:
            conn.rollback()
        flash(f"❌ Erreur système : {e}", 'danger')

    finally:
        if conn:
            conn.close()

    # passe filled_week au template (utilisé par la bannière d'info)
    return render_template(
        'rh/index.html',
        metrics=metrics,
        column_names=colnames,
        datetime=datetime,
        this_year=this_year,
        filled_week=banner_week
    )

# -----------------------------------------------------------------------------
# Routes : UPDATE
# -----------------------------------------------------------------------------
@rh_bp.route('/update/<string:id>', methods=['GET', 'POST'])
def update(id):
    conn = None
    metric = None
    this_year = current_year()

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        # ✅ Charger la ligne
        cur.execute("""
            SELECT 
               "ID" as id,
               "BU" as bu,
               "Production_line" as production_line,
               "DL_Headcount" as dl_headcount,
               "H100" as h100,
               ROUND(CAST(COALESCE("H125", 0.00) / 1.25 AS numeric), 2) AS h125,
               ROUND(CAST(COALESCE("H150", 0.00) / 0.5 AS numeric), 2) AS h150,
               ROUND(CAST(COALESCE("H200", 0.00) / 2 AS numeric), 2) AS h200,
               "WeekNo" as weekno,
               "Import_Date" as import_date,
               "Year" as year
            FROM weekly_dl_metrics
            WHERE "ID" = %s
        """, (id,))
        metric = cur.fetchone()

        # ❌ Si la ligne n'existe pas
        if metric is None:
            abort(404)

        # ❌ Interdire la modification si l'année n'est pas l'année courante
        if int(metric['year']) != this_year:
            flash(f"Modification non autorisée : seules les données de {this_year} sont modifiables.", "warning")
            abort(404)

        if request.method == 'POST':
            data = parse_form_data(request.form)

            # ✅ On ne touche pas Import_Date ni Year lors d’un update
            update_query = """
            UPDATE weekly_dl_metrics SET
              "BU"=%s, "Production_line"=%s, "DL_Headcount"=%s,
              "H100"=%s, "H125"=%s, "H150"=%s, "H200"=%s,
              "WeekNo"=%s
            WHERE "ID" = %s AND "Year" = %s
            """
            values = (
                data['bu'], data['production_line'], data['dl_headcount'],
                data['h100'], data['h125'], data['h150'], data['h200'],
                data['weekno'], id, this_year
            )
            cur.execute(update_query, values)

            if cur.rowcount == 0:
                conn.rollback()
                flash(f"Modification refusée : seules les données de {this_year} sont modifiables.", "danger")
                return redirect(url_for('rh.index'))

            conn.commit()
            flash('Métrique mise à jour avec succès !', 'success')
            return redirect(url_for('rh.index'))

    except (ValueError, psycopg2.Error) as e:
        if conn:
            conn.rollback()
        flash(f"Erreur lors de la modification : {e}", 'danger')
        return render_template('rh/update.html', metric=metric, this_year=this_year)
    finally:
        if conn:
            conn.close()

    return render_template('rh/update.html', metric=metric, this_year=this_year)
