"""
    DB interface script powered by WSGI
"""
# Script level 
import os, sys, getopt, csv, re, string, types, shutil;
pattern = re.compile('[\W_]+')
# Web level
import cgi, urllib, MySQLdb, json;
# ESRI Geographic data parser 
import shapefile
# File handling
import fnmatch
from StringIO import StringIO
from tempfile import mkdtemp
from zipfile import ZipFile

class WebDB:
    def __init__(self, base_dir, errors):
        # Setup base dir for reference later
        self.base_dir = base_dir
        
        # Connect to an existing database
        connParams = {}
        connParams["UID"] = "calswim"
        connParams["PWD"] = "xxx" 
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
        
    def delete_items(self, delete_ids):
        delete_query="DELETE FROM GeoData WHERE gd_id IN ("
        for id in delete_ids:
            delete_query += id+","
        delete_query = delete_query.rstrip(',') + ")"
        self.cursor.execute(delete_query)
                
    def get_items(self):
        # Get all records from DB
        select_query="SELECT gd_id, organization, project_name, project_name_short, project_description, data_type, data_target FROM GeoData ORDER BY gd_id DESC"        
        self.cursor.execute(select_query)

        # Compile all records into an HTML string        
        html_rows = "" 
        while(1):
            row=self.cursor.fetchone()
            if row == None:
                break            
            html_row = '<td><a href="/?login=admin&edit='+str(row[0])+'" target="_blank">Edit</a></td>'
            for html_item in row:
                html_row += "<td>"+str(html_item)+"</td>"
            html_rows += "<tr>"+html_row+"<td><input type='checkbox' name='deletes' value='"+str(row[0])+"'/></td></tr>"
        columns = ["<th>ID", "Organization", "Project Name", "Short Name", "Project Description","Data Type","Data Target","Delete</th>"]
        return "<thead><tr><th></th>"+ "</th><th>".join(columns) +"</tr></thead><tbody>"+ html_rows +"</tbody>"
    
    def html_filter(self, string):
        """
            Just apply <a> tags to E-Mails and URLs
        """
        words = string.split()
        for word in words:
            if re.search('^http:\/\/.*$', word):
                word = '<a href="%(url)s">%(url)s</a>' % {'url':word}
            if re.search('^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,4}$', word.upper()):
                word = '<a href="mailto:%(email)s">%(email)s</a>' % {'email':word}                    
        return ' '.join(words)
    
    def set_poly_geo(self,shp_file):        
        # Open shp_file with parser
        sf = shapefile.Reader(shp_file)
        # Get all shapes
        shapes = sf.shapes()
        # Iterate over shapes
        polygons=[]
        count = 0
        errors = []
        warnings = []
        for shape in shapes:
            count = count+1
            # Make sure the first and last set of coordinate are the same, closed polygon
            if shape.points[0] == shape.points[-1]:
                polygons.append(shape.points)
            else:
                warnings.append("WARNING:: Shape number %d is not an enclosed polygon. First and last coordinates should be the same. This was automatically corrected." % count)
                shape.points.append([shape.points[0][0],shape.points[0][1]])
                polygons.append(shape.points)
        
        if count == 0:
            errors.append("ERROR:: No valid shapes found.")
        
        count = 0;
        for poly in polygons:
            count = count+1
            if len(poly) < 1:
                errors.append("ERROR:: Shape number %d has no valid points." % count)
        return polygons,errors,warnings
     
    def find_shapefile(self, temp_dir):
        matches = []
        for root, dirnames, filenames in os.walk(temp_dir):
            for filename in fnmatch.filter(filenames, '*.shp'):
                matches.append(os.path.join(root, filename))
        return matches

    def import_data(self, form):
        """
            Simple function to inhale form data and insert it into the Database
        """
        error_msg = ""
        
        try:
            # Set insert order
            columns = "organization, contact, email, phone, data_url, \
            project_name_short, project_name, project_description, timeline_start, timeline_finish, project_funder,\
            data_target, location_description, site_count, data_collector, data_type, data_format, data_policies, \
            keyword, other, location, shp_file"
            
            # Gather submitted for values
            values = []
            # Source data
            values.append( '"%s"' % form.getvalue('organization') )
            values.append( '"%s"' % form.getvalue('contact') )
            values.append( '"%s"' % form.getvalue('email') )
            if form.getvalue('phone'):
                values.append( form.getvalue('phone') )
            else:
                values.append('NULL')
            values.append( '"%s"' % form.getvalue('source') )
            # Project data
            if len(form.getvalue('labelShort')) > 0:
                values.append( '"%s"' % form.getvalue('labelShort') )
            else:
                values.append( '"%s"' % form.getvalue('label') )
            values.append( '"%s"' % form.getvalue('label') )
            values.append( '"%s"' % form.getvalue('description') )        
            values.append( "STR_TO_DATE('"+ form.getvalue('timelineStart') +"', '%m/%d/%Y')" )
            values.append( "STR_TO_DATE('"+ form.getvalue('timelineFinish') +"', '%m/%d/%Y')" )
            values.append( '"%s"' % form.getvalue('funder') )
            # Meta data
            values.append( '"%s"' % form.getvalue('target') )
            values.append( '"%s"' % form.getvalue('locdescription') )
            values.append( form.getvalue('numsites') )
            values.append( '"%s"' % form.getvalue('collector') )
            values.append( '"%s"' % form.getvalue('datatype') )
            values.append( '"%s"' % form.getvalue('dataformat') )
            values.append( '"%s"' % form.getvalue('policies') )
            # Other Data
            values.append( '"%s"' % " ".join(pattern.sub(' ', form.getvalue('keyword')).split()) )
            values.append( '"%s"' % form.getvalue('other') )
            # Shape file data            
            zip_shp_file = form['shp_file'].file
            zip_shp_file_name = form.getvalue('shp_file')                    
            # Latitude/Longitude data
            lat = form.getvalue('lat')
            lng = form.getvalue('lng')
            
            # Build MySQL Geometry syntax
            locations = []
            json_data = ""
            if zip_shp_file_name:
                # Extract all files from compressed shapefile
                zip_shp_file_contents = zip_shp_file.read()
                with ZipFile(StringIO(zip_shp_file_contents), 'r') as zip_sf:
                    temp_dir = mkdtemp(dir=self.base_dir+"/tmp/")
                    zip_sf.extractall(path=temp_dir)
                    path_to_shapefile = self.find_shapefile(temp_dir)
                    
                    #json_data = {'message':'DEBUG::Temp Dir:'+temp_dir}
                    #self.return_message = json.dumps(json_data);
                    #return
                
                # Set POLYGON GEOMETRY from shp file
                polygons,errors,warnings = self.set_poly_geo(path_to_shapefile[0])                                    
                
                # Regardless of errors process polygons
                for polygon in polygons:
                    # Re-map polygon coordinates with spaces between lat and lng
                    for idx, val in enumerate(polygon):
                        # Reverse values so that latitude is first, then longitude
                        val.reverse()
                        polygon[idx] = " ".join( map( str, val) )
                    locations.append("GeomFromText('POLYGON((%s))')" % (",".join(polygon)))
                
                # Send errors, if any
                errors_warnings = errors + warnings
                html_errors = "<br>".join(errors_warnings)
                json_data = {'message':html_errors}
                self.return_message = json.dumps(json_data);
                
                # If there are errors, warnings are OK, then return without inserting
                if len(errors) > 0:                    
                    return
            elif lat and lng:
                # Set MySQL NULL value for shp contents
                zip_shp_file_contents = "NULL"
                # Set POINT GEOMETRY from latitude and longitude
                locations.append("GeomFromText('POINT("+lat+" "+lng+")')")            
            else:
                json_data = {'message':'ERROR:: No Shape File nor Coordinates were found.'}
                self.return_message = json.dumps(json_data);
                return
            
            # For each location insert details into DB
            count = 0
            if len(locations) < 1:
                json_data = {'message':'ERROR:: Coordinates were not found.'}
                self.return_message = json.dumps(json_data);
                return
                        
            for location in locations:
                if not location:
                    json_data = {'message':'ERROR:: Empty location.'}                    
                    self.return_message = json.dumps(json_data);
                    return
            
                # Init reusable list to append location and shapefile
                locs_shps = []
                count = count+1
                
                # Build MySQL insert query
                locs_shps.append(location)
                locs_shps.append( '"%s"' % self.db.escape_string(zip_shp_file_contents) )
                
                insert_query = "INSERT INTO calswim.GeoData ("+columns+") VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s);"
                insert_values = tuple(values+locs_shps)
                insert_query_with_values = insert_query % insert_values                
                self.cursor.execute(insert_query_with_values)
                if json_data == "":
                    json_data = {'message':'Data import successful'}                    
            
            # Commit queries
            self.db.commit()
            
            select_query = "SELECT LAST_INSERT_ID() as id"
            self.cursor.execute(select_query)
            row = self.cursor.fetchone()
            
            data_file = form['data_file']
            if data_file.filename:
                data_file_name = os.path.basename(data_file.filename)                
                
                download_dir = self.base_dir +"/downloads/"+ str(row[0]) +"/"                
                if not os.path.exists(download_dir):
                    os.makedirs(download_dir)
                                
                data_save_file = open(download_dir+data_file_name, "w")
                data_save_file.write(data_file.file.read())
                data_save_file.close
                
                update_query = """UPDATE calswim.GeoData SET data_url="%(PATH)s" WHERE gd_id=%(ID)s""" % {'PATH':"/downloads/"+ str(row[0]) +"/"+ data_file_name, 'ID':row[0]}
                self.cursor.execute(update_query)                
            
            # Return JavaScript boolean to view         
            self.return_message = json.dumps(json_data)
        except:
            e = sys.exc_info()[1]
            #json_data = {'message': error_msg+" "+str(e)}
            json_data = {'message': "ERROR:: Please try again."} 
            self.return_message = json.dumps(json_data)
            print >> self.errors, "ERROR:: "+error_msg+" "+str(e)
        
        # Delete temp files
        try:
            shutil.rmtree(temp_dir) # delete directory
        except:
            e = sys.exc_info()[1]
            print >> self.errors,"ERROR:: "+error_msg+" "+str(e)
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
    
    def set_data_details(self, gd_id, form):            
        try:
            # Gather submitted for values
            values = []
            update_query = "UPDATE GeoData SET "
            columns = ["organization","contact","email","phone","data_url","project_name_short","project_name","project_description","timeline_start","timeline_finish","project_funder","data_target","location_description","site_count","data_collector","data_type","data_format","data_policies","location","keyword","other"]
            for column in columns:
                if form.getvalue(column) == None or form.getvalue(column) == "":
                    update_query += column+"=NULL,"
                elif column == "location":
                    update_query += column+"=GeomFromText('"+form.getvalue(column)+"'),"
                elif column == "phone" or column == "site_count":
                    update_query += column+"="+form.getvalue(column)+","
                elif column == "timeline_start" or column == "timeline_finish":
                    update_query += column+"=STR_TO_DATE('"+ form.getvalue(column) +"', '%Y-%m-%d'),"
                else:
                    update_query += column+'="'+form.getvalue(column)+'",'
            
            update_query = update_query.rstrip(',') + " WHERE gd_id="+gd_id
            self.cursor.execute(update_query)
            # Close DB connections        
            self.cursor.close()
            json_data = {'message':"Success"}
            return_message = json.dumps(json_data);
            return return_message
        except:
            e = sys.exc_info()[1]
            print >> self.errors, "ERROR:: "+ str(e)
            return "ERROR::<br/>"+ str(e) +"<br/><br/>STATMENT::<br/>"+ update_query
        
    def get_data_details(self, gd_id, format='json'):
        # Select all details from table according to gd_id
        if format == "csv":
            # This is the CSV format, used for front end users to download details 
            select_query = """
            SELECT organization, contact,
            email,
            concat(left(phone,3),'-',mid(phone,4,3),'-',right(phone,4)) as phone, 
            data_url,        
            project_name, project_description,
            DATE_FORMAT( timeline_start, '%M %e, %Y') as timeline_start,
            DATE_FORMAT( timeline_start, '%M %e, %Y') as timeline_finish,
            project_funder, data_target, location_description, site_count, data_collector,
            data_type, data_format, data_policies, keyword, other
            FROM GeoData WHERE gd_id=""" + gd_id
            # Create a list of column names                
            labels = ["Organization","Contact","E-Mail","Phone","Data URL","Project Name","Project Description","Start Date","Finish Date","Project Funder","Data Target","Location Description","Site Count","Data Collector","Data Type","Data Format","Data Policies","Keywords","Other"]            
        elif format == "html":
            # This is the HTML format, used for editing details        
            select_query = """
            SELECT organization, contact,email,phone, data_url, project_name, project_name_short, project_description,
            timeline_start,timeline_finish,project_funder, data_target, location_description,
            site_count, data_collector,data_type, data_format, data_policies, AsText(location) as location, keyword, other
            FROM GeoData WHERE gd_id=""" + gd_id
            # Create a list of column names                
            labels = ["organization","contact","email","phone","data_url","project_name","project_name_short","project_description","timeline_start","timeline_finish","project_funder","data_target","location_description","site_count","data_collector","data_type","data_format","data_policies","location","keyword","other"]
        else:
            #This is the JSON format used for front end web queries
            select_query = """
            SELECT organization, contact,
            concat('<a href="mailto:',email,'">',email,'</a>') as email,
            concat(left(phone,3),'-',mid(phone,4,3),'-',right(phone,4)) as phone, 
            concat('<a href="',data_url,'" target="_blank">',data_url,'</a>') as data_url,        
            project_name, project_description,
            DATE_FORMAT( timeline_start, '%M %e, %Y') as timeline_start,
            DATE_FORMAT( timeline_start, '%M %e, %Y') as timeline_finish,
            project_funder, data_target, location_description, site_count, data_collector,
            data_type, data_format, data_policies, keyword, other
            FROM GeoData WHERE gd_id=""" + gd_id            
            # Create a list of column names                
            labels = ["Organization","Contact","E-Mail","Phone","Data URL","Project Name","Project Description","Start Date","Finish Date","Project Funder","Data Target","Location Description","Site Count","Data Collector","Data Type","Data Format","Data Policies","Keywords","Other"]            
            
        self.cursor.execute(select_query)
        row = self.cursor.fetchone()            
        
        # Return results
        if format == 'csv':
            buffer = StringIO()
            csv_model = csv.writer(buffer)            
            csv_model.writerow(labels)
            csv_model.writerow(row)
            return buffer.getvalue()
        elif format == 'html':            
            html_row = ""
            for index, item in enumerate(row):
                if labels[index] == "project_name_short":
                    project_name_short = item
                if item:
                    html_item = str(item)                
                else:
                    html_item = ""
                html_row += "<tr><td class='label' width='150px'>"+(labels[index].capitalize()).replace("_"," ")+"</td><td><textarea name='"+labels[index]+"'>"+html_item+"</textarea></td></tr>"            
            return "<h2>("+gd_id+") "+project_name_short+"</h2><form action='' method='post'><input class='button float-right margin-bottom' type='submit' name='submit' value='Update'/><thead><tr><th>Label</th><th>Data</th></tr></thead><tbody>"+ html_row +"</tbody></form>"
        else:        
            html_row = []
            for item in row:
                if item == None:
                    item = ""
                if isinstance(item, str):                
                    html_row.append("<br />".join(item.split("\n")))
                else:
                    html_row.append(str(item))
                            
            data_details = dict()
            for index,label in enumerate(labels):
                 data_details[index] = (label,html_row[index])            
            # Return raw json
            return json.dumps(data_details, sort_keys=True)
    
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
                                  SELECT gd_id, organization, project_name_short, project_name, project_description, data_type, data_target, AsText(location)
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
                                         MATCH (organization, contact, project_name, project_description, project_funder, data_target, location_description, data_collector, data_type, keyword, other)
                                         AGAINST ('%(KeywordQuery)s' IN BOOLEAN MODE)
                                      """ % {"KeywordQuery":keyword_query})
        else:
            # Search query does not have a specified location
            query_build.append("""
                                 SELECT gd_id, organization, project_name_short, project_name, project_description, data_type, data_target, AsText(location)
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
                                         MATCH (organization, contact, project_name, project_description, project_funder, data_target, location_description, data_collector, data_type, keyword, other)
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
            coordinates.append( str(row[7]).replace('POINT(','').replace('POLYGON((','').replace(')','') )
            rows.append( {"c":[{"v":row[0]}, {"v":row[1]}, {"v":row[2]}, {"v":row[3]}, {"v":row[4]}, {"v":row[5]}, {"v":row[6]}]} )
    
        # Return search values as json
        cols = [{"id":'gd_id', "label":'gd_id', "type":'string'},
                {"id":'organization', "label":'Organization', "type":'string'},
                {"id":'project_short', "label":'Project Short', "type":'string'},
                {"id":'project', "label":'Project', "type":'string'},
                {"id":'description', "label":'Description', "type":'string'},                
                {"id":'target', "label":'Target', "type":'string'}]
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
