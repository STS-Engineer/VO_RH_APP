# rh_bp.py

from flask import Flask, render_template, request, redirect, url_for, flash, abort
import psycopg2 # type: ignore
import psycopg2.extras # type: ignore
from datetime import datetime
import psycopg2.errors  # type: ignore
from config import Config



# Initialisation de l'application
from flask import Blueprint
rh_bp = Blueprint('rh', __name__, template_folder='templates')

# ====================================================================
# FONCTION DE CONNEXION PSYCOPG2
# ====================================================================

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

# ====================================================================
# FONCTION UTILITAIRE (sert uniquement pour update)
# ====================================================================

def parse_form_data(form):
    """Extrait et convertit les données du formulaire pour l'UPDATE (sans modifier import_date ni year)."""
    return {
        'id': form['id'],
        'bu': form['bu'],
        'production_line': form['production_line'],
        'dl_headcount': int(form['dl_headcount']),
        'h100': float(form['h100']),
        'h125': float(form['h125'])* 1.25,
        'h150': float(form['h150'])* 0.5,
        'h200': float(form['h200'])* 2,
        'weekno': form['weekno']
    }

# ====================================================================
# ROUTES FLASK : INDEX (INSERT, SELECT)
# ====================================================================


@rh_bp.route('/', methods=['GET', 'POST'])
def index():
    conn = None
    metrics = []
    column_names = ["ID", "BU", "Production_line", "DL_Headcount", "H100", "H125", "H150", "H200", "WeekNo", "Import_Date", "Year"]

    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        if request.method == 'POST':
            try:
                # ✅ Lignes fixes Valeo et Nidec
                lines_valeo = ["FLEX","MNG2","FP","GENII R","GENII C","BUA","VM4"]
                lines_nidec = ["NEM2","SIM AS","SKP42","NGMAP","POWERTOOLS","10T","11TA","DCK","CM3","CM4","FAIX"]

                weekno = request.form['weekno']
                import_date = datetime.now().date()  # ✅ automatique à la saisie
                year = datetime.now().year          # ✅ automatique à la saisie

                # === Valeo ===
                for line in lines_valeo:
                    dl_headcount = int(request.form.get(f"{line}_dl_headcount", 0) or 0)
                    h100 = float(request.form.get(f"{line}_h100", 0) or 0)
                    h125 = float(request.form.get(f"{line}_h125", 0) or 0) * 1.25
                    h150 = float(request.form.get(f"{line}_h150", 0) or 0) * 0.5
                    h200 = float(request.form.get(f"{line}_h200", 0) or 0) * 2

                    cur.execute("""
                        INSERT INTO weekly_dl_metrics 
                        ("BU","Production_line","DL_Headcount","H100","H125","H150","H200","WeekNo","Import_Date","Year")
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """, ("VALEO", line, dl_headcount, h100, h125, h150, h200, weekno, import_date, year))

                # === Nidec ===
                for line in lines_nidec:
                    dl_headcount = int(request.form.get(f"{line}_dl_headcount", 0) or 0)
                    h100 = float(request.form.get(f"{line}_h100", 0) or 0)
                    h125 = float(request.form.get(f"{line}_h125", 0) or 0)* 1.25
                    h150 = float(request.form.get(f"{line}_h150", 0) or 0)* 0.5
                    h200 = float(request.form.get(f"{line}_h200", 0) or 0)* 2
                    cur.execute("""
                        INSERT INTO weekly_dl_metrics 
                        ("BU","Production_line","DL_Headcount","H100","H125","H150","H200","WeekNo","Import_Date","Year")
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """, ("NIDEC", line, dl_headcount, h100, h125, h150, h200, weekno, import_date, year))

                conn.commit()
                flash("Toutes les lignes Valeo + Nidec ont été enregistrées avec succès !", "success")
                return redirect(url_for('rh.index'))  # ✅ Redirection après succès
                
            except psycopg2.errors.UniqueViolation:
                conn.rollback()
                flash(f"⚠️ Erreur : Des données existent déjà pour la semaine {weekno}. Veuillez modifier les données existantes.", 'warning')
            except ValueError as ve:
                conn.rollback()
                flash(f"❌ Erreur de saisie : Veuillez vérifier que tous les champs numériques sont corrects. Détails : {ve}", 'danger')
            except psycopg2.Error as db_error:
                conn.rollback()
                flash(f"❌ Erreur de base de données : {db_error}", 'danger')

        # ✅ Récupération des données existantes (toujours exécutée)
        select_query = """
        SELECT "ID", "BU", "Production_line", "DL_Headcount",
            "H100",
            COALESCE("H125",0) / 1.25 as "H125",
            COALESCE("H150",0) / 0.5 as "H150",
            COALESCE("H200",0) / 2 as "H200",
            "WeekNo", "Import_Date", "Year"
        FROM weekly_dl_metrics
        ORDER BY "Import_Date" DESC, "WeekNo" DESC
        """

        cur.execute(select_query)
        metrics = cur.fetchall()
        
    except Exception as e:
        if conn: 
            conn.rollback()
        flash(f"❌ Erreur système : {e}", 'danger')
        
    finally:
        if conn: 
            conn.close()

    return render_template('rh/index.html', metrics=metrics, column_names=column_names, datetime=datetime)


# ====================================================================
# ROUTES FLASK : UPDATE
# ====================================================================

@rh_bp.route('/update/<string:id>', methods=['GET', 'POST'])
def update(id):
    conn = None
    metric = None
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

        if request.method == 'POST':
            data = parse_form_data(request.form)

            # ✅ On ne touche pas Import_Date ni Year lors d’un update
            update_query = """
            UPDATE weekly_dl_metrics SET
            "BU"=%s, "Production_line"=%s, "DL_Headcount"=%s,
            "H100"=%s, "H125"=%s, "H150"=%s, "H200"=%s,
            "WeekNo"=%s
            WHERE "ID" = %s
            """
            values = (
                data['bu'], data['production_line'], data['dl_headcount'],
                data['h100'], data['h125'], data['h150'], data['h200'],
                data['weekno'], id
            )
            cur.execute(update_query, values)
            conn.commit()
            flash('Métrique mise à jour avec succès !', 'success')
            return redirect(url_for('rh.index'))

        # ✅ Récupération pour affichage du formulaire update
        cur.execute("""
            SELECT 
               "ID" as id,
               "BU" as bu,
               "Production_line" as production_line,
               "DL_Headcount" as dl_headcount,
               "H100"as h100,
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

        if metric is None:
            abort(404)

    except (ValueError, psycopg2.Error) as e:
        if conn: conn.rollback()
        flash(f"Erreur lors de la modification : {e}", 'danger')
        return render_template('rh/update.html', metric=metric)
    finally:
        if conn: conn.close()

    return render_template('rh/update.html', metric=metric)

# ====================================================================
# MAIN
# ====================================================================

