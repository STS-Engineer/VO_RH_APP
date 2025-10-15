# voh_bp.py

from flask import Flask, render_template, request, redirect, url_for, flash, abort
import psycopg2  # type: ignore
import psycopg2.extras  # type: ignore
from datetime import datetime
from config import Config
import psycopg2.errors  # type: ignore

from flask import Blueprint
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

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        if request.method == 'POST':
            try:
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
                year = datetime.now().year

                # ✅ Récupérer le prochain ID avant insertion
                cur.execute('SELECT COALESCE(MAX("ID"), 0) + 1 FROM public.weekly_voh_metrics')
                next_id = cur.fetchone()[0]

                # === Fonction d’insertion ===
                def insert_lines(bu, lines):
                    nonlocal next_id
                    for line in lines:
                        dl_headcount = int(request.form.get(f"{line}_dl_headcount", 0) or 0)
                        h100 = float(request.form.get(f"{line}_h100", 0) or 0)
                        h125 = float(request.form.get(f"{line}_h125", 0) or 0) * 1.25
                        h150 = float(request.form.get(f"{line}_h150", 0) or 0) * 0.5
                        h200 = float(request.form.get(f"{line}_h200", 0) or 0) * 2
                        type_value = TYPE_MAP.get(line, "VOH")

                        cur.execute("""
                            INSERT INTO public.weekly_voh_metrics
                            ("ID", "BU", "Department_function", "Type", "DL_Headcount",
                             "H100", "H125", "H150", "H200", "WeekNo", "Import_Date", "Year")
                            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        """, (
                            next_id, bu, line, type_value, dl_headcount,
                            h100, h125, h150, h200, weekno, import_date, year
                        ))

                        next_id += 1  # auto incrémentation manuelle

                # Insertion des lignes
                insert_lines("VALEO", lines_valeo)
                insert_lines("NIDEC", lines_nidec)
                insert_lines("OTHER", lines_other)

                conn.commit()
                flash("✅ Toutes les lignes ont été enregistrées avec succès !", "success")
                return redirect(url_for('voh.index'))

            except psycopg2.errors.UniqueViolation:
                conn.rollback()
                flash(f"⚠️ Erreur : Des données existent déjà pour la semaine {weekno}.", 'warning')
            except ValueError as ve:
                conn.rollback()
                flash(f"❌ Erreur de saisie : {ve}", 'danger')
            except psycopg2.Error as db_error:
                conn.rollback()
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

    except Exception as e:
        if conn:
            conn.rollback()
        flash(f"❌ Erreur système : {e}", 'danger')
        return redirect(url_for('voh.index'))

    finally:
        if conn:
            conn.close()

    return render_template('voh/index.html', metrics=metrics, column_names=column_names, datetime=datetime)


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
                "BU"=%s, "Department_function"=%s,"Type"=%s, "DL_Headcount"=%s,
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
        if conn:
            conn.rollback()
        flash(f"Erreur lors de la modification : {e}", 'danger')
        return render_template('voh/update.html', metric=metric)
    finally:
        if conn:
            conn.close()

    return render_template('voh/update.html', metric=metric)
