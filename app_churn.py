import json, uuid, simplify

from flask import Flask, request, jsonify


def beaconMerchantRelation(beacon_id, namespace):
    merchant_id = namespace_to_merchant.find_one({'namespace':namespace})['merchant_id']
    found  = beacon_to_merchant.find_one({"beacon_id":beacon_id, "merchant_id": ObjectId(merchant_id)})
    if found:
        return True
    return False

def orderAtBeacon(beacon_id):
    order_id =  beacon_status.find_one({"beacon_id":beacon_id})
    if order_id:
        return True
    return False

def getTaxForBeaconId(beacon_id):
    merchant_id = beacon_to_merchant.find_one({'beacon_id':beacon_id})['merchant_id']
    return merchant_info.find_one({"_id":ObjectId(merchant_id)})['tax']

def setOrder(order):
    beacon_id = order['beacon_id']
    namespace = order['namespace']
    if beaconMerchantRelation(beacon_id, namespace):
        # if its a first time order
        if not orderAtBeacon(beacon_id):
            order_id = str(uuid.uuid1())
            beacon_status.insert_one({"beacon_id":beacon_id, "order_id" : order_id})
        else:
            order_id = beacon_status.find_one({"beacon_id":beacon_id})['order_id']
        order_updated = order['selected_items']
        for x in order_updated:
            print order_updated
            x["claimed"]= 0
            x['users'] = []

        transactions.insert_one({"order_id": order_id,
         "beacon_id" : beacon_id,
         "selected_items":order_updated,
         "timestamp":order['timestamp'],
         "payment_status":{"number_of_users":0, "current_total_":0, "users":{},'paid':0},
         "running_total":calculateTotalForOrder(order['selected_items'],beacon_id )
        })

def calculateTotalForUserTemp(item_list, tax):
    to_be_paid_by_user = 0
    for an_item in item_list:
        to_be_paid_by_user += an_item['times']*an_item['price']

    total_without_tax = to_be_paid_by_user

    total = (1+tax)*total_without_tax
    return total

def calculateTotalForUser(item_list,namespace):
    to_be_paid_by_user = 0
    print item_list
    for an_item in item_list:
        to_be_paid_by_user += an_item['times']*an_item['price']

    total_without_tax = to_be_paid_by_user

    merchant_id = namespace_to_merchant.find_one({'namespace':namespace})['merchant_id']
    i= merchant_info.find_one({"_id": ObjectId(merchant_id)})
    tips = i['tips']
    tax= i['tax']
    total = total_without_tax*(1+tax)
    return {"total_without_tax": total_without_tax, "tax": tax*total_without_tax, "suggested_tip": [{x:x*total} for x in tips] }


def calculateTotalForOrder(order, beacon_id):
    total = 0
    for item in order:
        total += item['times']*item['price']

    tax = getTaxForBeaconId(beacon_id)
    return total*(1+tax)


# called from setItems()
# needs to update payment status for the beacon_id
def setUserTotal(total, beacon_id, user_id):
    order_id = data['beacon_status'][beacon_id]
    data['transactions'][order_id]['payment_status']['users'][user_id] = {'to_pay': total['total_without_tax'] + total['tax'], "paid":0}


def getTotalSelected(dict_of_users):
    total = 0
    for user in dict_of_users:
        total += dict_of_users[user]['to_pay']
    return total

#simplify access
def payment(token_id, amount, user_id):
    info  ={"amount":amount, "token_id":"f21da65e-f0ab-45cb-b8e6-40b493c3671f", "currency":"USD","description":"app_test","reference":user_id}
    pay = simplify.Payment.create(info)

    if pay.paymentStatus == "APPROVED":
        return True
    return False

def getKeys(namespace):
    merchant_id = namespace_to_merchant.find_one({'namespace':namespace})['merchant_id']
    merchant = merchant_info.find_one({"_id":ObjectId(merchant_id)})
    return merchant['public_key'], merchant['private_key']


app = Flask(__name__)

#accept information in json format
#this is the first interaction between POS software and the server
#POS software takes input from waiter and calls this endpoint
#input--> beacon_id, order, timestamp; order --> {'dish':{'times':, "price":, "claimed_by":0},...}
#output --> None; it is just used to set the order
@app.route("/acceptOrder", methods = ['GET','POST'])
def acceptOrder():
    order = request.get_json()
    print order
    setOrder(order)
    return jsonify({"success":1})


#this is the point where server interacts with the user to show the items ordered on that id
#input--> beacon_id
#output--> all items i.e. order as defined above
@app.route("/displayOrder", methods= ['GET', 'POST'])
def displayOrder():
    beacon_id = request.get_json()['beacon_id']
    order_id = beacon_status.find_one({"beacon_id": beacon_id})
    if order_id:
        order_id = order_id['order_id']
        items =transactions.find_one({"order_id": order_id})['selected_items']
        return jsonify({"items": items})
    else:
        return jsonify({"status":"No one at the table"})

#it is the second step in interaction of user with the server
#user sets the item and submits the data to this endpoint
#it also generates user_id for that transaction so that number of users associated to that beacon can be counted
#input --> {"beacon_id":"#1","namespace":,"user_id":uid ,"selected_items":[{"name":"dish1", "times":number_of_times,"price":price},{"name": "dish2","times":number_of_times,"price":price}]}
#sets the transaction's payment status with user id in the payment_status
#output--> calculated total; total_without_tax, tax, tips
@app.route("/setItems", methods=['GET', 'POST'])
def setItems():
    item_list = request.get_json()
    beacon_id = item_list['beacon_id']
    user_id = item_list['user_id']
    namespace = item_list['namespace']
    order_id = beacon_status.find_one({"beacon_id":beacon_id})
    if order_id:
        order_id = order_id['order_id']
        order  = transactions.find_one({"order_id":order_id})

        for item in item_list['selected_items']:
            for x,order_no in enumerate(order['selected_items']):
                if order_no['name'] == item['name']:
                    order_no['claimed'] += item['times']
                    order_no['users'].append(user_id)


        order['payment_status']['users'][user_id] = item_list['selected_items']
        for user in order['payment_status']['users']:
            order['payment_status']['current_total_'] += calculateTotalForUserTemp(order['payment_status']['users'][user], getTaxForBeaconId(beacon_id))

        order['payment_status']['users'][user_id] ={"selected_items": item_list['selected_items']}

        total =  calculateTotalForUser(order['payment_status']['users'][user_id]['selected_items'],namespace)
        order['payment_status']['users'][user_id]['to_pay'] = total['total_without_tax'] + total['tax']
        order['payment_status']['users'][user_id]['paid'] = 0
        transactions.update({"order_id":order_id}, {"$set":{"order":order}})
        return jsonify(total)
    else:
        return jsonify({"status":"No one at the table"})

# when the sum of items selected by users amounts to actual total then show button
#input :  beacon_id
#output: true/false
# whenever someone sets item --> app will call this endpoint to check
@app.route('/showPayButton', methods = ['GET','POST'])
def showPayButton():
    beacon_id = request.get_json()['beacon_id']
    order_id = beacon_status.find_one({"beacon_id":beacon_id})
    if order_id:
        transaction = transactions.find_one({"order_id":order_id['order_id']})
        if transaction['running_total'] == transaction['payment_status']['current_total_']:
            return jsonify({"show": 1})
        return jsonify({"show":0})
    else:
        return jsonify({"status":"No one at the table"})

# called when the payment is made i.e. showPayButton and eventually payment went through
# input --> {"beacon_id":"#1"}
@app.route('/clearBeaconId', methods =['GET', 'POST'])
def clearBeaconId():
    beacon_id = request.get_json()['beacon_id']
    order_id = beacon_status.find_one({"beacon_id": beacon_id})
    beacon_history.update_one({"beacon_id":beacon_id},{"$push":{"orders":order_id}})
    transactions.update({"order_id":order_id}, {"$set":{'payment_status.paid':1}})
    beacon_status.update({"beacon_id":beacon_id,"order_id":None})
    return jsonify({"success":1})

# this is when user presses the pay button and the app gets the token from simplify which is then given to server
# to request the payment
#input : {"token": , "beacon_id":"#1", "amount": ,"namespace": , "user_id":} ; check at the app if tip is not negative
#output: {"success":}, ; also updates the user_id['paid'] =1 and updates the view
@app.route('/submitPayment', methods =['GET','POST'])
def submitPayment():
    pay_info = request.get_json()
    public_key , private_key = getKeys(pay_info['namespace'])
    simplify.public_key = public_key
    simplify.private_key = private_key
    token_id = pay_info['token']
    beacon_id = pay_info['beacon_id']
    order_id = beacon_status.find_one({"beacon_id":beacon_id})
    user_id = pay_info['user_id']
    if order_id:
        paid = payment(token_id,pay_info['amount'], user_id)
        if paid.paymentStatus == "APPROVED":
            #update transactions['payment_status']['users'][user_id]['paid']= 1
            transactions.update({"order_id":order_id},{"$set":{"payment_status.users"+ user_id+ ".paid":1 }})
            #return payment_status
            return jsonify({'success':1})
        else:
            return jsonify({"success":0})
    else:
        return jsonify({"status":"No one at the table"})

# when the user refreshes the app he shoudl see the updated claims
#input --> {"beacon_id": ,"namespace": }
@app.route('/showPaymentStatus', methods=['GET','POST'])
def showPaymentStatus():
    beacon_id = request.get_json()['beacon_id']
    order_id = beacon_status.find_one({"beacon_id":beacon_id})
    if order_id:
        order_id = order_id['order_id']
        return jsonify(transactions.find_one({"order_id":order_id})['payment_status'])
    else:
        return jsonify({"status":"No one at the table"})

# give the public key
#input --> "namespace"
@app.route('/getPublicKey', methods= ['GET','POST'])
def getPublicKey():
    namespace = request.get_json()['namespace']
    merchant_id =  namespace_to_merchant.find_one({"namespace":namespace})['merchant_id']
    return jsonify({"key":merchant_info.find_one({"_id":ObjectId(merchant_id)})['public_key']})

@app.route('/show_data', methods=['GET','POST'])
def show_data():
    return jsonify(data)

if __name__=="__main__":
    from pymongo import MongoClient
    from bson.objectid import ObjectId
    client = MongoClient()
    database = client['app']

    # tables
    transactions =  database['transactions']
    merchant_info = database['merchant_info']
    beacon_to_merchant = database['beacon_to_merchant']
    beacon_status = database['beacon_status']
    namespace_to_merchant = database['namespace_to_merchant']
    beacon_history = database['beacon_history']

    app.debug =True
    app.run('0.0.0.0', port = 9090)
