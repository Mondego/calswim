"""
    ========================================================
    * CalSWIM index (root controller) powered by WSGI *
    ========================================================
"""
import os;
import cgi;
import urllib;
from view import WebView;
from db import WebDB;

def application(environ, start_response):
    
    """
        ==========================================================        
        * Logic for determining web view content is located here *
        ==========================================================
    """
    
    # Retrieve GET variables and store them as a dictionary
    form = cgi.FieldStorage(fp=environ['wsgi.input'], environ=environ)
       
    # Initialize web classes
    CalSwimView = WebView(os.path.dirname(__file__), environ['wsgi.errors'])    
    CalSwimDB = WebDB(environ['wsgi.errors']);
    #print >> CalSwimView.errors, "Print Error Message In Apache Logs"
    
    """
        ================================================
        * Main switch to determine controller/template *
        ================================================
    """
    if 'get_map_locs' in form:
        """
            Return AJAX call results for Google Map Pins
        """
        CalSwimView.set_search(form.getvalue('get_map_locs'),form.getvalue('radius'),form.getvalue('keywords'))
        CalSwimView.content = CalSwimDB.get_map_locs(CalSwimView)    
    elif 'import_data' in form:
        """
            Handle AJAX call for data import into DB
        """        
        CalSwimDB.import_data(form)
        CalSwimView.content = CalSwimDB.return_message
    elif 'get_data_details' in form:
        """
           Return AJAX call results for data details
        """
        dataID = form.getvalue('get_data_details')
        
        if 'format' in form:
            format = form.getvalue('format')
        else:
            format = 'json'        
        CalSwimView.content = CalSwimDB.get_data_details(dataID, format)
        
        if format != 'json':
            # Define headers and return content
            start_response('200 OK', [('content-type', 'application/CSV'),('Content-Disposition','attachment; filename=ecodata'+dataID+'.csv')])
            return CalSwimView.content
    else:        
        CalSwimView.set_content('index')
        CalSwimView.content = CalSwimView.content % {'uploadResult' : ""}
    
    # Define headers and return content
    start_response('200 OK', [('content-type', 'text/html')])
    return CalSwimView.content
