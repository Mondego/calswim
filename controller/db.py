"""
    DB interface script powered by WSGI
"""
# Script level 
import os
import sys
import getopt
import csv
# Web level
import cgi;
import urllib;
import MySQLdb;
import json;
import re, string;
pattern = re.compile('[\W_]+')
# ESRI Geographic data parser 
import shapefile
from StringIO import StringIO

class WebDB:
    def __init__(self, errors):
        # Connect to an existing database
        connParams = {}
        connParams["UID"] = "calswim"
        connParams["PWD"] = "calswim2012"
        connParams["HOST"] = "localhost"
        connParams["PORT"] = 3306
        connParams["DSN"] = "calswim"        
    
        # Open database connection
        self.db = MySQLdb.connect(connParams["HOST"],connParams["UID"],connParams["PWD"],connParams["DSN"],connParams["PORT"])        
        # prepare a cursor object using cursor() method
        self.cursor = self.db.cursor()  
        # Set return message to blank
        self.return_message = ""
        # Initialize error var
        self.errors = errors  
    
    def set_poly_geo(self,shp_file):        
        # Open shp_file with parser
        sf = shapefile.Reader(shp=shp_file)
        # Get all shapes
        shapes = sf.shapes()
        # Iterate over shapes
        polygons=[]
        for shape in shapes:
            polygons.append(shape.points)
        return polygons
     
    def import_data(self, form):
        """
            Simple function to inhale form data and insert it into the Database
        """
#        try:
        # Set insert order
        columns = "contact, source, label, description, keyword, other, location, shp_file"            
        
        # Gather submitted for values
        values = []
        values.append( form.getvalue('contact') )
        values.append( form.getvalue('source') )
        values.append( form.getvalue('label') )
        values.append( form.getvalue('description') )
        values.append( " ".join(pattern.sub(' ', form.getvalue('keyword')).split()) )
        values.append( form.getvalue('other') )
        
        # Build MySQL Geometry syntax
        shp_file = form['shp_file'].file
        shp_file_name = form.getvalue('shp_file')
        lat = form.getvalue('lat')
        lng = form.getvalue('lng')
        if shp_file_name:
            # Get shp file contents to be stored as a blob
            shp_file_contents = shp_file.read()
            # Set POLYGON GEOMETRY from shp file
            polygons = self.set_poly_geo(StringIO(shp_file_contents))            
            locations = []
            for polygon in polygons:
                for idx, val in enumerate(polygon):
                    polygon[idx] = " ".join( map( str, polygon[idx]) )
                locations.append("GeomFromText('POLYGON((%s))')" % (",".join(polygon)))
        elif lat and lng:
            # Set MySQL NULL value for shp contents
            shp_file_contents = "NULL"
            # Set POINT GEOMETRY from latitude and longitude
            locations = ["GeomFromText('POINT("+lat+" "+lng+")')"]            
        else:
            json_data = {'message':'ERROR:: No Shape File nor Coordinates were found.'}
            self.return_message = json.dumps(json_data);
            return
        
        # For each location insert details into DB
        count = 0
        for location in locations:
            count = count+1
            # Build MySQL insert query
            mysql_values = "'"+ "','".join(values)  +"',"+ location +",'"+ self.db.escape_string(shp_file_contents) +"'"
            insert_query = "INSERT INTO calswim.GeoData (%(columns)s) VALUES(%(values)s);"
            insert_query = insert_query % {"columns":columns, "values":mysql_values}
            print >> self.errors, str(count)+" INSERT QUERY:: "+insert_query+"\n"
            self.cursor.execute(insert_query)
        
        # Commit queries
        self.db.commit()
        
        # Return JavaScript boolean to view 
        json_data = {'message':'Data import successful'}
        self.return_message = json.dumps(json_data);
#        except:
#            e = sys.exc_info()[1]
#            self.return_message = e;
            
        # Close DB connections        
        self.cursor.close()
    
    def process(self, file_name):
        csv_reader = csv.reader(open(file_name, 'rb'), delimiter=' ', quotechar='|')
        for row in csv_reader:
            columns = "source_name,site_name,description,urllink,latitude,longitude"
            lat = convert_coordinates(row.pop(2))
            lng = convert_coordinates(row.pop(2))
    
            values = "'"+ "','".join(row) +"',"+ lat +","+ lng
            insert_query = "INSERT INTO calswim.coordinate (%(columns)s) VALUES(%(values)s);"
            insert_query = insert_query % {"columns":columns, "values":values}
            self.cursor.execute(insert_query)
            #print mysql_insert_row
    
    def convert_coordinates(self, deg_min_sec):
        deg, min, sec  = deg_min_sec.split()
        return str(float(deg) + (float(min)/60) + (float(sec)/3600));            
    
    def get_map_locs(self, CalSwimView):
        """
            This is a simple script to query the database.
            We need this so that ajax can pull data
        """
        # Initialize query list
        query_build = []
        
        if (CalSwimView.lat and CalSwimView.lng):            
            # Search query has a specified location thus check against intersection of points and polygons in database
            self.cursor.execute("SET @center = GeomFromText('POINT(%s %s)');",(float(CalSwimView.lat), float(CalSwimView.lng)))
            self.cursor.execute("SET @radius = %s;",(CalSwimView.radius))
            self.cursor.execute("""
                                   SET @bbox = CONCAT('POLYGON((',
                                       X(@center) - @radius, ' ', Y(@center) - @radius, ',',
                                       X(@center) + @radius, ' ', Y(@center) - @radius, ',',
                                       X(@center) + @radius, ' ', Y(@center) + @radius, ',',
                                       X(@center) - @radius, ' ', Y(@center) + @radius, ',',
                                       X(@center) - @radius, ' ', Y(@center) - @radius, '))'
                                   );
                               """)
            query_build.append("""
                                  SELECT contact, description, source, AsText(location)
                                  FROM GeoData
                                  WHERE Intersects( location, GeomFromText(@bbox) )
                                  AND
                                      CASE geometrytype(location)
                                          WHEN 'POINT' THEN
                                              SQRT(POW( ABS( X(location) - X(@center)), 2) + POW( ABS(Y(location) - Y(@center)), 2 )) < @radius
                                          ELSE
                                              TRUE
                                      END
                               """)
            # Search query has at least 1 keyword
            if len(CalSwimView.keywords) > 0:
                # Just a few MySQL notes:
                #    Default MySQL operation executes an "OR" search among terms
                #    To make sure all terms are in a given result, "AND" search among terms, then just add prefix "+" before each term
                #    To exclude results with a given term, just add prefix "-" before the term
                keyword_query = "*, ".join(CalSwimView.keywords) +"*"        
                query_build.append("""                          
                                         AND
                                         MATCH (contact,label,description,keyword,other)
                                         AGAINST ('%(KeywordQuery)s' IN BOOLEAN MODE)
                                      """ % {"KeywordQuery":keyword_query})
        else:
            # Search query does not have a specified location
            query_build.append("""
                                 SELECT contact, description, source, AsText(location)
                                 FROM GeoData
                              """)
            # Search query has at least 1 keyword
            if len(CalSwimView.keywords) > 0:
                # Just a few MySQL notes:
                #    Default MySQL operation executes an "OR" search among terms
                #    To make sure all terms are in a given result, "AND" search among terms, then just add prefix "+" before each term
                #    To exclude results with a given term, just add prefix "-" before the term
                keyword_query = "*, ".join(CalSwimView.keywords) +"*"        
                query_build.append("""                          
                                         WHERE
                                         MATCH (contact,label,description,keyword,other)
                                         AGAINST ('%(KeywordQuery)s' IN BOOLEAN MODE)
                                      """ % {"KeywordQuery":keyword_query})
        select_query = "\n".join(query_build)
        #print >> CalSwimView.errors, select_query
        
        # execute SQL query using execute() method.
        self.cursor.execute(select_query)

        # Fetch a single row using fetchone() method.
        rows = []    
        table_data = {}
        coordinates = []
        while(1):
            row=self.cursor.fetchone()
            if row == None:
                break
            coordinates.append( str(row[3]).replace('POINT(','').replace('POLYGON((','').replace(')','') )
            rows.append( {"c":[{"v":row[0]}, {"v":row[1]}, {"v":row[2]}]} )
    
        # Return search values as json
        cols = [{"id":'source', "label":'Source', "type":'string'}, {"id":'description', "label":'Description', "type":'string'}, {"id":'url', "label":'URL', "type":'string'}]    
        table_data["cols"] = cols
        table_data["rows"] = rows
        # Assign table data to json table data container
        json_data = {}
        json_data["table_data"] = table_data
        json_data["coordinates"] = coordinates
        
        # Close DB connections        
        self.cursor.close()
        
        # Return results
        return json.dumps(json_data)

if __name__ == "__main__":
    # parse command line options
    try:
        opts, args = getopt.getopt(sys.argv[1:], "h", ["help"])
    except getopt.error, msg:
        print msg
        print "for help use --help"
        sys.exit(2)
    # process options
    for o, a in opts:
        if o in ("-h", "--help"):
            #print __doc__
            print "Usage::\n\tpython db.py csv_file.csv"
            sys.exit(0)
    # process arguments
    CalSwimDB = WebDB()
    for arg in args:
        CalSwimDB.process(arg)      
