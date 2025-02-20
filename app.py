import os
from time import strftime
from flask import Flask,render_template, request, url_for,session,redirect,make_response,jsonify
from os.path import join, dirname, realpath
from importlib import import_module
from werkzeug.utils import secure_filename
import datetime
import calendar
import uuid
import sqlite3 as sql
import json
# import cv2
import adminconfig
import base64
import pandas as pd



db_file = "database.db"
excel_file1 = "product_tracking_usa.csv"

# Check if database exists
if not os.path.isfile(db_file):
    # Read Excel file
    df1 = pd.read_csv(excel_file1)
    df1.columns = [col.replace(" ", "_") for col in df1.columns]
    
    conn = sql.connect(db_file)  # Create database
    df1.to_sql("Basicdata", conn, if_exists="replace", index=False)  # Create table
    
    conn.execute('CREATE TABLE IF NOT EXISTS Users (Name TEXT NOT NULL, Username TEXT NOT NULL, Password TEXT NOT NULL,Role TEXT NOT NULL)')
    conn.execute('''
    CREATE TABLE IF NOT EXISTS OrderRequest (
        RNo INTEGER PRIMARY KEY AUTOINCREMENT,
        RequestBy TEXT NOT NULL,
        AvailableCount INTEGER NOT NULL,
        RequestedCount INTEGER NOT NULL,
        Status TEXT NOT NULL)
    ''')
    print("Database created and table inserted!")
else:
    conn = sql.connect(db_file)  # Just connect if it exists
    
    print("Connected to existing database!")
conn.close()


with sql.connect("database.db") as con:
  cur = con.cursor()

  username=adminconfig.ADMIN_USERNAME
  password = adminconfig.ADMIN_PASSWORD
  cur.execute("SELECT * FROM Users WHERE Username=(?) AND Password=(?)",[(username),(password)])
  userdata = cur.fetchone()
  if userdata==None:
    name=adminconfig.ADMIN_NAME
    # email=adminconfig.ADMIN_EMAIL
    # phone=adminconfig.ADMIN_PHONENO
    role=adminconfig.ADMIN_ROLE
    cur.execute("INSERT INTO Users (Name,Username,Password,Role) VALUES (?,?,?,?)",(name,username,password,role))

    users_data=adminconfig.usersdata
    print(users_data)
    for user_data in users_data:
      name, username1, password1, role = user_data
      print(user_data)
      cur.execute("INSERT INTO Users (Name, Username, Password, Role) VALUES (?, ?, ?, ?)",(name, username1, password1, role))

app = Flask(__name__)
now = datetime.datetime.now()
s=str(now)


@app.route("/")
def index():
    if "device_id" in session:
        return redirect(url_for('home'))
    else:
        return render_template('login.html',user_exists=None, invalid = None, logged_out=None)
    
@app.route('/login', methods=['GET', 'POST'])
def login():
  invalid = None
  if request.method == 'POST':
    username = request.form['username']
    password = request.form['password']
    with sql.connect("database.db") as con:
        cur = con.cursor()
        #Validate user credentails from database
        cur.execute("SELECT * FROM Users WHERE Username=(?) AND Password=(?)",[(username),(password)])
        userdata = cur.fetchone()
        session['userdata']=userdata
        print(session['userdata'])

        if userdata!=None:
            # session['team']=userdata[4]
            session['logged_out'] = None
            device_id = str(uuid.uuid4())
            device_id = request.remote_addr
            session["device_id"] = device_id
            resp = make_response(redirect("/home"))
            resp.set_cookie("device_id", device_id)
            return resp
        else:
            invalid=1

    return render_template('login.html',user_exists=None, invalid = invalid, logged_out=None)

@app.route('/home', methods = ['POST', 'GET'])
def home():
    if "device_id" not in session:
        return redirect("/")
    userdata = session.get('userdata')
    print(userdata)
    with sql.connect("database.db") as con:
        cur = con.cursor()
        if userdata[3]=="Admin":
          data = []
          itc=0
          dc=0
          # 1. Stock count (Products not out for delivery)
          stock_count_query = """
          SELECT COUNT(Product_ID) AS Stock_Count
          FROM Basicdata
          WHERE Out_for_Dealer_Date IS NULL OR Out_for_Dealer_Date = '';
          """
          stock_count = cur.execute(stock_count_query).fetchone()[0]

          # 2. Number of unique dealers
          unique_dealers_query = """
          SELECT COUNT(DISTINCT Dealer_Name) AS Number_of_Dealers FROM Basicdata;
          """
          num_dealers = cur.execute(unique_dealers_query).fetchone()[0]

          
          # Execute query
          cur.execute("""
              SELECT 
                  Dealer_Name, 
                  SUM(CASE WHEN Sale_Date IS NULL OR Sale_Date = '' THEN 1 ELSE 0 END) AS not_sold_count,
                  SUM(CASE WHEN Sale_Date IS NOT NULL AND Sale_Date != '' THEN 1 ELSE 0 END) AS sold_count
              FROM Basicdata
              GROUP BY Dealer_Name
          """)

          # Fetch results
          dealer_data = cur.fetchall()

          # Convert into a list of dictionaries for easy use
          dealer_list = [
              {"Dealer_Name": row[0], "Not_Sold": row[1], "Sold": row[2]}
              for row in dealer_data if row[0] is not None
              ]

          print("Unique Medical Rep Data:", dealer_list)

          cur.execute("SELECT RNo,RequestBy, RequestedCount FROM OrderRequest WHERE Status = ?", ("Open",))
          requestdata = cur.fetchall()

          cur.execute("SELECT * FROM OrderRequest")
          requestcheck = cur.fetchall()

          return render_template('home.html',stock_count=stock_count,unique_mr_count=num_dealers,userdata=userdata,unique_mr_list=dealer_list,requestdata=requestdata)
        else:
          data = []
          cur.execute("""
              SELECT 
                  SUM(CASE WHEN Sale_Date IS NULL OR Sale_Date = '' THEN 1 ELSE 0 END) AS not_sold_count,
                  SUM(CASE WHEN Sale_Date IS NOT NULL AND Sale_Date != '' THEN 1 ELSE 0 END) AS sold_count
              FROM Basicdata
              WHERE Dealer_Name = ?
          """, (userdata[0],))

          result = cur.fetchone()  # Fetch the result as a tuple

          
          return render_template('home_rep.html',data=result,userdata=userdata)



@app.route('/orderrequest', methods=['GET', 'POST'])
def orderrequest():
    userdata = session.get('userdata')
    

    with sql.connect("database.db") as con:
        cur = con.cursor()
        cur.execute("""
            SELECT 
                SUM(CASE WHEN Sale_Date IS NULL OR Sale_Date = '' THEN 1 ELSE 0 END) AS not_sold_count
            FROM Basicdata
            WHERE Dealer_Name = ?
        """, (userdata[0],))
        data = cur.fetchone()

    return render_template('request.html', data=data[0] if data else 0, userdata=userdata)

@app.route('/ordered', methods=['POST'])
def ordered():
    userdata = session.get('userdata')
    

    availablecount = request.form.get('availablecount')
    requestcount = request.form.get('requestcount')
    status = "Open"

    with sql.connect("database.db") as con:
        cur = con.cursor()
        cur.execute("""
            INSERT INTO OrderRequest (RequestBy, AvailableCount, RequestedCount, Status)
            VALUES (?, ?, ?, ?)
        """, (userdata[0], availablecount, requestcount, status))
        con.commit()  # Commit transaction

    return redirect(url_for('home'))



@app.route('/approval', methods=['GET'])
def approval():
    rno = request.args.get('rno')  # Request number from URL
    dname = request.args.get('dname')  # Dealer Name from URL
    countinc = int(request.args.get('countinc'))  # Number of products to update

    with sql.connect("database.db") as con:
        cur = con.cursor()

        # Update OrderRequest status to 'Approved'
        cur.execute("UPDATE OrderRequest SET Status = 'Approved' WHERE RNo = ?", (rno,))
        
        # Fetch Dealer State
        cur.execute("SELECT Dealer_State FROM Basicdata WHERE Dealer_Name = ? LIMIT 1", (dname,))
        dealer_state_row = cur.fetchone()
        if not dealer_state_row:
            return "Dealer not found", 400  # Handle case where dealer is not found

        dealer_state = dealer_state_row[0]
        current_date = datetime.datetime.now().strftime('%Y-%m-%d')  # Get today's date

        # Select 'countinc' number of products that are not sold yet
        cur.execute("""
            SELECT S_No FROM Basicdata
            WHERE Dealer_Name IS NULL AND (Sale_Date IS NULL OR Sale_Date = '')
            LIMIT ?
        """, (countinc,))
        products_to_update = cur.fetchall()

        if not products_to_update:
            return "No available products to update", 400  # Handle no products found

        # Update the selected products with OutForSale_Date, Dealer Name, and Dealer State
        cur.executemany("""
            UPDATE Basicdata
            SET Out_For_Dealer_Date = ?, Dealer_Name = ?, Dealer_State = ?
            WHERE S_No = ?
        """, [(current_date, dname, dealer_state, row[0]) for row in products_to_update])

        con.commit()  # Commit changes

    return redirect(url_for('home'))  # Redirect to the appropriate page after approval



     

@app.route('/deliver', methods=['GET', 'POST'])
def deliver():
    userdata = session.get('userdata')
    with sql.connect("database.db") as con:
      cur = con.cursor()
      cur.execute("""
              SELECT 
                  SUM(CASE WHEN Sale_Date IS NULL OR Sale_Date = '' THEN 1 ELSE 0 END) AS not_sold_count
              FROM Basicdata
              WHERE Dealer_Name = ?
          """, (userdata[0],))
      data=cur.fetchone()
    return render_template('deliver.html',data=data[0],userdata=userdata)


@app.route('/deliveryupdate', methods=['GET', 'POST'])
def deliveryupdate():
    deliverycount = int(request.form['deliverycount'])  # Number of products to update
    customername = request.form['customername']  # Customer Name
    userdata = session.get('userdata')  # Get session user data
    dealer_name = userdata[0]  # Dealer Name

    current_date = datetime.datetime.now().strftime('%Y-%m-%d')  # Get today's date

    with sql.connect("database.db") as con:
        cur = con.cursor()

        # Fetch the Dealer's State
        cur.execute("SELECT Dealer_State FROM Basicdata WHERE Dealer_Name = ? LIMIT 1", (dealer_name,))
        dealer_state_row = cur.fetchone()
        if not dealer_state_row:
            return "Dealer not found", 400  # Handle case where dealer is not found

        dealer_state = dealer_state_row[0]

        # Get Not Sold Products (limit by deliverycount)
        cur.execute("""
            SELECT S_No FROM Basicdata
            WHERE Dealer_Name = ? AND (Sale_Date IS NULL OR Sale_Date = '')
            LIMIT ?
        """, (dealer_name, deliverycount))

        products_to_update = cur.fetchall()

        if not products_to_update:
            return "No unsold products available", 400  # Handle no products found

        # Update the Sale Date, Customer Name, and Customer State for the selected products
        cur.executemany("""
            UPDATE Basicdata
            SET Sale_Date = ?, Customer_Name = ?, Customer_State = ?
            WHERE S_No = ?
        """, [(current_date, customername, dealer_state, row[0]) for row in products_to_update])

    return redirect(url_for('home'))  # Redirect after approval


@app.route('/dashboardview')
def dashboardview():
    powerbi_url = "https://app.powerbi.com/groups/me/reports/e5ead2a6-8d6a-447e-9642-a713b3206519/eb97c4782ae7a57e7e8d?experience=power-bi"
    return redirect(powerbi_url)


@app.route('/tracking_update/<idno>')
def tracking_update(idno):
  with sql.connect("database.db") as con:
      cur = con.cursor()
      
      labelid = cur.fetchone()
      userdata = session.get('userdata')
      return render_template('update.html',label_no=idno,label_id=labelid,userdata=userdata)


@app.route('/logout')
def logout():
    session.pop("device_id", None)
    resp = make_response(redirect("/"))
    resp.delete_cookie("device_id")
    return resp

@app.route('/load/<section>')
def load_section(section):
      return redirect(url_for('labels', section=section))

@app.route('/labels/<section>')
def labels(section):
  userdata = session.get('userdata')
  with sql.connect("database.db") as con:
    cur = con.cursor()
    if userdata[3]=="Admin" and section=='all':
      data = []
      cur.execute("SELECT * FROM Basicdata ORDER BY Label_No DESC")
      label_data = cur.fetchall()
      return render_template('labels.html',data=label_data,userdata=userdata)
    elif userdata[3]=="Admin" and section=='intransit':
      data = []
      cur.execute("SELECT * FROM Basicdata WHERE Delivery_Status=(?) ORDER BY Label_No DESC",[('In transit')])
      label_data = cur.fetchall()
      return render_template('labels.html',data=label_data,userdata=userdata)
    elif userdata[3]=="Admin" and section=='delivered':
      data = []
      cur.execute("SELECT * FROM Basicdata WHERE Delivery_Status=(?) ORDER BY Label_No DESC",[('Delivered')])
      label_data = cur.fetchall()
      return render_template('labels.html',data=label_data,userdata=userdata)
    elif userdata[3]=="Medical Rep" and section=='intransit':
      data = []
      cur.execute("SELECT * FROM Basicdata WHERE Delivery_Status=(?) AND Medical_Rep=(?) ORDER BY Label_No DESC",[('In transit'),(userdata[0])])
      label_data = cur.fetchall()
      return render_template('labels.html',data=label_data,userdata=userdata)
    elif userdata[3]=="Medical Rep" and section=='delivered':
      data = []
      cur.execute("SELECT * FROM Basicdata WHERE Delivery_Status=(?) AND Medical_Rep=(?) ORDER BY Label_No DESC",[('Delivered'),(userdata[0])])
      label_data = cur.fetchall()
      return render_template('labels.html',data=label_data,userdata=userdata)
            
        
           

@app.route('/tracking_details/<idno>')
def tracking_details(idno):
  with sql.connect("database.db") as con:
      cur = con.cursor()
      #check if User already present
      cur.execute("SELECT * FROM Trackingdata WHERE Label_No=(?)",[(idno)])
      datas=cur.fetchall()


      cur.execute("SELECT * FROM Handlingdata WHERE Label_No=(?)",[(idno)])
      handledata = cur.fetchall()

      # Initialize the result dictionary
      result_dict = {
          "Status": [],         # List to store status values
          "Medical_Rep": None,  # Placeholder for Medical Rep
          "Recipient_Name": "-"  # Default to "-" if no recipient name found
      }

      # Process the fetched data
      for row in handledata:
          box_opened = row[2]  # Box Opened (Assuming 4th index)
          status = row[4]      # Status (Assuming 7th index)
          medical_rep = row[3]  # Medical Rep (Assuming 6th index)
          recipient_name = row[5]  # Recipient Name (Assuming 8th index)
          print(box_opened)
          print(medical_rep)
          
          # Update Status list
          if "Customer Visit" in status and box_opened == "Yes":
              result_dict["Status"].append("Opened - In transit")
          elif "Customer Visit" in status and box_opened == "No":
              if result_dict["Status"][-1] != "In transit":
                result_dict["Status"].append("In transit")
          else:
              result_dict["Status"].append(status)


          # Assign Medical_Rep (taking the first non-null value)
          if medical_rep and result_dict["Medical_Rep"] is None:
              result_dict["Medical_Rep"] = medical_rep

          # Assign Recipient_Name (taking the first non-null value)
          if recipient_name and recipient_name != "None":
              result_dict["Recipient_Name"] = recipient_name
      print(result_dict)
      
      return render_template('details.html',data=datas,result_dict=result_dict)



      

@app.route('/labelupdate', methods=['GET', 'POST'])
def labelupdate():
    if "update" in request.form:
      labelno = request.form['labelno']
      labelid = request.form['labelid']
      customername=request.form['customername']
      deliverystatus=request.form['deliverystatus']
      medicalrep=request.form['medicalrep']
      boxopened=request.form['boxopened']

      if deliverystatus=='Yes':
         deliverystatus='Delivered'
         recipient=customername
      else:
         deliverystatus=f'Customer Visit - {customername}'
         recipient=None
      
      
      with sql.connect("database.db") as con:
        cur = con.cursor()
        cur.execute("INSERT INTO Handlingdata(Label_No, Label_ID,Box_Opened,Medical_Rep,Status,Recipient_Name) VALUES (?,?,?,?,?,?)",(labelno,labelid,boxopened,medicalrep,deliverystatus,recipient))
        if deliverystatus=='Yes':
           cur.execute("""
            UPDATE Basicdata 
            SET Delivery_Status = 'Delivered' 
            WHERE Label_No = ?;
        """, (labelno,))
        return redirect(url_for('home'))



@app.route('/close/<id>')
def close(id):
  session['idd']=id
  with sql.connect("database.db") as con:
    cur = con.cursor()
    cur.execute("SELECT Trial_No FROM Trips WHERE Id=(?)",[(id)])
    data=cur.fetchone()
    trialno=(data[0])
    cur.execute("UPDATE Trips SET Closed = 'Closed' WHERE Trial_No = (?)",[(trialno)])
    return redirect(url_for('home'))














app.secret_key = "123"
if __name__ == '__main__':
    app.run(debug=True)





