from flask import Flask, flash, redirect, render_template, request, session, url_for, jsonify
from flask_session import Session
from passlib.apps import custom_app_context as pwd_context
from functools import wraps
from tempfile import gettempdir
from urllib.parse import urlparse
from decimal import *
import passlib.pwd as pwd
import sqlalchemy
import os
import psycopg2
import gviz_api

app = Flask(__name__)

url = urlparse(os.environ["DATABASE_URL"])
conn = psycopg2.connect(
 database=url.path[1:],
 user=url.username,
 password=url.password,
 host=url.hostname,
 port=url.port
)

class SQL(object):
    """Wrap SQLAlchemy to provide a simple SQL API."""

    def __init__(self, url):
        """
        Create instance of sqlalchemy.engine.Engine.

        URL should be a string that indicates database dialect and connection arguments.

        http://docs.sqlalchemy.org/en/latest/core/engines.html#sqlalchemy.create_engine
        """
        try:
            self.engine = sqlalchemy.create_engine(url)
        except Exception as e:
            raise RuntimeError(e)

    def execute(self, text, *multiparams, **params):
        """
        Execute a SQL statement.
        """
        try:

            # bind parameters before statement reaches database, so that bound parameters appear in exceptions
            # http://docs.sqlalchemy.org/en/latest/core/sqlelement.html#sqlalchemy.sql.expression.text
            # https://groups.google.com/forum/#!topic/sqlalchemy/FfLwKT1yQlg
            # http://docs.sqlalchemy.org/en/latest/core/connections.html#sqlalchemy.engine.Engine.execute
            # http://docs.sqlalchemy.org/en/latest/faq/sqlexpressions.html#how-do-i-render-sql-expressions-as-strings-possibly-with-bound-parameters-inlined
            statement = sqlalchemy.text(text).bindparams(*multiparams, **params)
            result = self.engine.execute(str(statement.compile(compile_kwargs={"literal_binds": True})))

            # if SELECT (or INSERT with RETURNING), return result set as list of dict objects
            if result.returns_rows:
                rows = result.fetchall()
                return [dict(row) for row in rows]

            # if INSERT, return primary key value for a newly inserted row
            elif result.lastrowid is not None:
                return result.lastrowid

            # if DELETE or UPDATE (or INSERT without RETURNING), return number of rows matched
            else:
                return result.rowcount

        # if constraint violated, return None
        except sqlalchemy.exc.IntegrityError:
            return None

        # else raise error
        except Exception as e:
            raise RuntimeError(e)



db = SQL(os.environ["DATABASE_URL"])

app.config["SESSION_FILE_DIR"] = gettempdir()
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)


def login_required(f):
    """
    Decorate routes to require login.

    http://flask.pocoo.org/docs/0.11/patterns/viewdecorators/
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("user_id") is None:
            return "sorry"
        return f(*args, **kwargs)
    return decorated_function



@app.route("/", methods=["GET", "POST"])
def index(message=""):
    if request.method == "POST":
        exists = db.execute("SELECT EXISTS(SELECT * FROM bookings WHERE date = :date)",
                                date = request.form.get("date")
                                )
        if exists[0]['exists'] == False:
            return render_template("sorry.html", error = "Sorry, but no booking was found on that date.")
        
        booking = db.execute("SELECT * FROM bookings WHERE date = :date",
                                date = request.form.get("date")
                                )
        if len(request.form.get('code')) == 7:
            for row in booking:
                if row['bookcode'] == request.form.get('code'):
                    if session.get("admin") != 1:
                        session["user_id"] = 0
                        session["admin"] = 0
                        session["bookingid"] = row['id']
                    return redirect(url_for('appraisal'))
            return render_template("sorry.html", error = "Sorry that code doesn't match a booking on that date.") 
        
        
        
        elif len(request.form.get('code')) == 5:
            for row in booking:
                if row['delcode'] == request.form.get('code'):
                    if session.get("admin") != 1:
                        session["user_id"] = 0
                        session["admin"] = 0
                        session["bookingid"] = row['id']
                    return redirect(url_for('mq'))
            return render_template("sorry.html", error = "Sorry that code doesn't match a booking on that date.")
        
        else:
            return render_template("sorry.html", error = "Sorry that code is incorrect.")
        
    else:
        return render_template("signin.html")


@app.route("/adminlogin", methods=["GET", "POST"])
def adminlogin(message=""):
    if request.method == "POST":
        if not request.form.get("username"):
            return render_template("adminlogin.html", message = "Username required.")
        elif not request.form.get("password"):
            return render_template("adminlogin.html", message = "Password required.")
        
        ver = db.execute("SELECT * FROM users WHERE username = :username", username = request.form.get("username"))
        if len(ver) != 1 or not pwd_context.verify(request.form.get("password"), ver[0]["hash"]):
            return render_template("adminlogin.html", message = "Incorrect password or nonexistant Username")
        
        else:
            session["user_id"] = ver[0]["id"]
            session["admin"] = 1
            return redirect(url_for("admin"))
            
    else:
        if session.get('user_id') != None and session.get('admin') == 1:
            return redirect(url_for('admin'))
        
        return render_template('adminlogin.html')
    

@app.route("/logout")
@login_required
def logout():
    
    session.clear()
    return redirect(url_for("index"))


@app.route("/admin", methods=["GET"])
@login_required
def admin(message=""):
    if session.get("admin") != 1:
        return "Unauthorised"
    
    elif request.args.get("start") != None and request.args.get("end") != None:
        bookings = db.execute("SELECT bookings.id, bookings.date, bookings.course, courses.name AS course FROM bookings INNER JOIN courses ON bookings.course=courses.id WHERE date BETWEEN :start AND :end",
                                start = request.args.get("start"),
                                end = request.args.get("end")
                                )
        
        calobject = list();
        for row in bookings:
            tempdict = {'id': row["id"], 'title': row["course"], 'allDay': 'true', 'start': row["date"]}
            exists = db.execute("SELECT EXISTS(SELECT id FROM metrics WHERE bookingid = :bookingid)",
                                bookingid = row["id"]
                                )
            if exists[0]['exists'] == False:
                tempdict['color'] = 'red'
            else:
                tempdict['color'] = 'green'
                
            calobject.append(tempdict)
            
        return jsonify(calobject)
        
    else:    
        return render_template("admin.html")


@app.route("/mq", methods=["GET", "POST"])
@login_required
def mq(message=""):
    if request.method == "POST":
        db.execute("INSERT INTO metrics (bookingid, q1, q2, q3, q4, q5, q6, q7, q8, q9, q10 , q11, q12, q13) VALUES (:bookingid, :q1, :q2, :q3, :q4, :q5, :q6, :q7, :q8, :q9, :q10 , :q11, :q12, :q13)",
                        bookingid = session.get("bookingid"),
                        q1 = request.form.get("q1"),
                        q2 = request.form.get("q2"),
                        q3 = request.form.get("q3"),
                        q4 = request.form.get("q4"),
                        q5 = request.form.get("q5"),
                        q6 = request.form.get("q6"),
                        q7 = request.form.get("q7"),
                        q8 = request.form.get("q8"),
                        q9 = request.form.get("q9"),
                        q10 = request.form.get("q10"),
                        q11 = request.form.get("q11"),
                        q12 = request.form.get("q12"),
                        q13 = request.form.get("q13")
                        )
        
        session.clear()
        return redirect(url_for('thankyou'))
    
    elif session['admin'] == 1:
        return "No questionaire for admin"
    
    else:
        booking = db.execute("SELECT bookings.id, bookings.date, courses.name AS course, trainers.name AS trainer FROM bookings INNER JOIN courses ON bookings.course=courses.id INNER JOIN trainers ON bookings.trainer=trainers.id WHERE bookings.id = :bookingid",
                                bookingid = session.get("bookingid")
                                )
        return render_template("mq.html", booking = booking[0])
    
@app.route("/thankyou", methods=["GET"])
def thankyou(message=""):
    session.clear()
    return render_template("thankyou.html")

@app.route("/appraisal", methods=["GET", "POST"])
@login_required
def appraisal(message=""):
    if request.args.get("id") != None:
        if session.get('admin') != 1:
            return "sorry unauthorised"
        else:
            session['bookingid'] = request.args.get("id")
            
    responses = db.execute("SELECT COUNT(*) FROM metrics WHERE bookingid = :bookingid",
                                bookingid= session.get("bookingid")
                                )
    booking = db.execute("SELECT bookings.id, bookings.date, courses.name AS course, trainers.name AS trainer FROM bookings INNER JOIN courses ON bookings.course=courses.id INNER JOIN trainers ON bookings.trainer=trainers.id WHERE bookings.id = :bookingid",
                                bookingid = session.get("bookingid")
                                )
    rawq12 = db.execute("SELECT q12 FROM metrics WHERE bookingid = :bookingid",
                                bookingid = session.get("bookingid"),
                                )
    q12 = []
    for i in rawq12:
        if i['q12'] != '':
            q12.append(i)
    
    return render_template("appraisal.html", booking = booking[0], responses = responses[0]['count'], q12 = q12)

@app.route("/data", methods=["GET", "POST"])
@login_required
def data(message=""):
    if request.method == "GET":
        if request.args.get('q') != None:
            schema = [("label", "string"),
                      ("value", "number")
                     ]

            data = [["Excellent", 0],
                    ["Good", 0],
                    ["Satisfactory", 0],
                    ["Below Average", 0],
                    ["Poor", 0]
                   ] 
            
            
            qs = request.args.get("q")
            qs = list(qs)
            j = 0
            a = 0
            questions = ""
            for i in qs:
                j = j + 1
                if i == "1":
                    if a != 0:
                        questions = questions + ","
                    a = a + 1
                    questions = questions + "q" + str(j)
            
                
            sqlarg = "SELECT " + questions + " FROM metrics WHERE bookingid = :bookingid"

            metrics = db.execute(sqlarg,
                                        bookingid = session.get('bookingid')
                                        )
            for row in metrics:
                for val in row.items():
                    i = val[1] - 1
                    j = 4 - i
                    data[j][1] += 1
            
            for val in data:
                try:
                    val[1] = val[1] / (len(metrics) * a) * 100
                except: val[1] = 0
                    
            data_table = gviz_api.DataTable(schema)
            data_table.LoadData(data)

            return data_table.ToJSon()
        
        elif request.args.get('improv') == "1":
            schema = [("label", "string"),
                      ("low", "number"),
                      ("open", "number"),
                      ("close", "number"),
                      ("high", "number")
                     ]
            improv = db.execute("SELECT q13 FROM metrics WHERE bookingid = :bookingid",
                                    bookingid = session.get('bookingid')
                                    )
            
            data = []
            i = 0
            for row in improv:
                try:
                    vals = row['q13'].split(',')
                except:
                    vals= [0,0]
                delegate = "Del" + str(i + 1)
                low = int(vals[0])
                high = int(vals[1])
                
                data.append([delegate,low,low,high,high])
                i = i + 1
                
            if len(data) < 6:
                for i in range(len(data),6):
                    delegate = "Del" + str(i + 1)
                    data.append([delegate,0,0,0,0])
                
            data_table = gviz_api.DataTable(schema)
            data_table.LoadData(data)

            return data_table.ToJSon()
            #return render_template("test.html", test=improv)
            
        else:
            return "error"    

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port,debug=False)