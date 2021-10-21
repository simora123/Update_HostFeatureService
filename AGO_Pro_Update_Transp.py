"""-------------------------------------------------------------------------------
Name:       AGO_Pro_Update.py
Purpose:    Overwrite services in ArcGIS Online or Enterprise utilizing ArcGIS Pro Maps
Verion:     4.0 Rev version.  For ArcGIS Online, publishes Hosted Feature Services only.
            For ArcGIS Enterprise, it depends on where the data resides and how that data is
            registered with ArcGIS Server.  If you have a connection to an SDE Enterprise
            Geodatabase registered, this will be a non-Hosted feature service.  If you do not
            have the connection registered, it will be Hosted.
            how your data is registered within ArcGIS Server--app
Updated:    06/25/2019
Comments:   Removed publish sd item out of try/except.  Experienced inconsistent behaviors in environments
            utilizing Active Directory Federated Services (ADFS) integration with Portal.
            Improved publishing process when services have same relative name.
            Account for connectionreset errors.
Author:     Alexander J Brown - Solution Engineer Esri (alexander_brown@esri.com)
-------------------------------------------------------------------------------"""
# import all the necessary modules
import arcgis
from arcgis.gis import GIS
import arcpy
import logging
import csv
import re
import os
import sys
import time
import configparser
import datetime
from datetime import datetime
from logging import handlers


# Logging function to establish where script logging will occur.
def logging_start(name):
    try:
        master_log = logging.getLogger()
        # Change logging level here (CRITICAL, ERROR, WARNING, INFO or DEBUG)
        master_log.setLevel(logging.INFO)

        if name.endswith('.py'):
            fname = name[:-3]
        else:
            fname = name
            pass

        # Logging variables
        max_bytes = 250000
        backup_count = 1  # Max number appended to log files when MAX_BYTES reached
        log_file = os.path.abspath(os.path.dirname(sys.argv[0])) + os.sep + 'Logs' + os.sep + fname + '.txt'

        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

        fh = logging.handlers.RotatingFileHandler(log_file, 'a', max_bytes, backup_count)
        # Change logging level here for log file (CRITICAL, ERROR, WARNING, INFO or DEBUG)
        fh.setLevel(logging.INFO)
        fh.setFormatter(formatter)
        master_log.addHandler(fh)

        return master_log

    except:
        error = 'Error: %s %s' % (sys.exc_info()[0], sys.exc_info()[1])
        raise error


# Parse through config file for all license types, workspace, output oracle table.
def get_config(location, name):
    try:
        config = configparser.ConfigParser()
        format_name = name[:-3]
        config.read(location + os.sep + format_name + '.cfg')
        agol_url = config.get('URL', 'agol_org')
        user_name = config.get('Credentials', 'user_name')
        pass_word = config.get('Credentials', 'pass_word')
        project_location = config.get('Project', 'location')
        organization = config.get('Sharing', 'org')
        everyone = config.get('Sharing', 'everyone')
        groups = config.get('Sharing', 'groups')
        ago_folder = config.get('Sharing', 'folder')
        options = config.get('Capabilities', 'options')
        open_data = config.get('OpenData_Category', 'category')
        logger.info('Parsed all variables from config file.')
        return agol_url, user_name, pass_word, project_location, organization, everyone, groups, ago_folder, options, open_data

    except configparser.Error as error:
        logger.critical('Check get config function: %s' % error)
        logger.critical('Check your config file!')


# Main script to call functions & execute publishing process
if __name__ == "__main__":
    # Auto Determine where the file location the script was placed, establish location, name, output csv
    scriptLocation = os.path.abspath(os.path.dirname(sys.argv[0])) + os.sep + 'Config'
    scriptName = os.path.basename(sys.argv[0])
    csv_path = os.path.abspath(os.path.dirname(sys.argv[0])) + os.sep + 'Logs\AGO_Pro_Update_Times.csv'
    file_exists = os.path.isfile(csv_path)

    # Start Logging
    logger = logging_start(scriptName)
    logger.info('**** Script: %s, was started. ****' % scriptName)
    print('**** Script: %s, was started. ****' % scriptName)
    start_time = time.strftime('%X %x %Z')

    # Parse through config file
    portal, user, password, project, shrOrg, shrEveryone, shrGroups, agol_folder, service_capabilities, open_cat = \
        get_config(scriptLocation, scriptName)

    # Set up feature service capabilitiy dictionary
    option_dict = dict()
    option_dict['capabilities'] = service_capabilities

    # Sign into default portal using ArcPY to ensure proper licensing for Pro
    try:
        arcpy.SignInToPortal(portal, user, password)
    except(arcpy.ExecuteError, arcpy.ExecuteWarning) as e:
        logger.error('Could not sign into Portal: %s' % e)
        sys.exit(1)

    # Set the path to the project
    prjPath = project

    # Local paths to create temporary content
    relPath = sys.path[0] + '/' + 'tempDir'

    # Set your environment and read in maps from ArcGIS Pro
    try:
        arcpy.env.overwriteOutput = True
        prj = arcpy.mp.ArcGISProject(prjPath)
        mp = prj.listMaps()
    except (arcpy.ExecuteError, arcpy.ExecuteWarning) as e:
        print(e)
        logger.error('Could not Open Project and list maps. Check your project path. %s' % e)
        print('Could not Open Project and list maps. Check your project path. %s' % e)
        logger.critical('---- Script Exited Before Finishing ----')
        sys.exit('---- Script Exited Before Finishing ----Could not connect to Pro Project')

    # Login to an existing organization
    try:
        gis = GIS(portal, user, password)
        logger.info('Successfully connected to %s' % gis)
        print('Successfully connected to %s' % gis)
    except RuntimeError as e:
        logger.critical('Please check your url in %s.cfg' % (scriptName[:-3]))
        logger.critical('Please check your credentials in %s.cfg' % (scriptName[:-3]))
        logger.critical('---- Script Exited Before Finishing ----')
        sys.exit('---- Script Exited Before Finishing ----Could not connect to ArcGIS Online')

    try:
        # Creates a folder the given folder name from config file. Does nothing if the folder already exists.
        # If owner is not specified, owner is set as the logged in user.
        gis.content.create_folder(folder=agol_folder, owner=user)
        logger.info('Portal Folder: %s' % agol_folder)
    except RuntimeError as e:
        logger.error('Please check your folder name in %s.cfg' % (scriptName[:-3]))

    # IF folder is not set in config, default to root directory
    if agol_folder == '':
        agol_folder = '/'
    elif agol_folder == ' ':
        agol_folder = '/'
    elif agol_folder is None:
        agol_folder = '/'


    # Loop through each map within the Pro Project.  Make sure map name is identical to feature service rest URL set
    # for the service
    for pro_map in mp:
        logger.info('Processing "%s"...' % str(pro_map.name))
        print('Processing "%s"...' % str(pro_map.name))

        # Set variables for sd draft and sd
        draftName = str(pro_map.name) + '.sddraft'
        sdName = str(pro_map.name) + '.sd'
        sddraft = os.path.join(relPath, draftName)
        sd = os.path.join(relPath, sdName)
        sd_fs_name = str(pro_map.name)

        # If output csv that logs publishing times exists, open it.  If not, create & write header.
        if file_exists is True:
            output_file = open(csv_path, 'a')
        else:
            output_file = open(csv_path, 'a')
            output_file.write('LogTime, Org, Service, Type, Duration(Min:Sec:Millsec)\n')
            print('Writing header...')

        # Create SD Draft
        try:
            sharing_draft = pro_map.getWebLayerSharingDraft("HOSTING_SERVER", "FEATURE", sd_fs_name)
            # Legacy
            # The arcpy.sharing module was introduced at ArcGIS Pro 2.2 to provide a better experience when
            # sharing web layers over the previously existing function CreateWebLayerSDDraft.
            # arcpy.mp.CreateWebLayerSDDraft(pro_map, sddraft, sd_fs_name,'MY_HOSTED_SERVICES','FEATURE_ACCESS',
            # True, True)
        except (arcpy.ExecuteError, arcpy.ExecuteWarning) as e:
            logger.error(e)

        # Export SD Draft
        try:
            sharing_draft.exportToSDDraft(sddraft)
            # Legacy
            # The arcpy.sharing module was introduced at ArcGIS Pro 2.2 to provide a better experience when
            # sharing web layers over the previously existing function CreateWebLayerSDDraft.
            # arcpy.mp.CreateWebLayerSDDraft(pro_map, sddraft, sd_fs_name,'MY_HOSTED_SERVICES','FEATURE_ACCESS',
            # True, True)
        except (arcpy.ExecuteError, arcpy.ExecuteWarning) as e:
            logger.error('Could not create SDDraft. Check permissions to script folder: %s' % e)
            logger.error(e)


        # Stage service in temporary location
        try:
            arcpy.StageService_server(sddraft, sd)
        except (arcpy.ExecuteError, arcpy.ExecuteWarning) as e:
            logger.error('Could not stage service. Check staging location: %s' % e)

        logger.info('SD File Created.')
        print('SD File Created.')
        logger_key = 0

        # Find the SD, update it, publish /w overwrite and set sharing and metadata
        try:
            sdItem = gis.content.search("{} AND owner:{}".format(sd_fs_name, user), item_type="Service Definition")
            print('List Returned for Service Definition search: %s' % sdItem)
            for i, value in enumerate(sdItem):
                match = re.search(r'\"(.*)\"', str(value)).group(1)
                print(match)
                print(sd_fs_name)
                if match == sd_fs_name:
                    n = i
            try:
                print("*************  1  ***************")
                sdItem = sdItem[n]
                sc = datetime.now()  # Current Datetime
                update_dict = {'capabilities':'Query,Extract'}
                try:
                    sdItem.update(data=sd)
                    logger.info('Uploading new Service Definition...')
                    print('Uploading new Service Definition...')
                    last = datetime.now() - sc  # Difference in time
                except ConnectionResetError as e:
                    logger.error(e)
                    sdItem.update(data=sd)

                # Write publishing time to output csv
                org = str(gis).split("@")[1].split("//")[1].split(".")[0]
                output = str(time.strftime('%X %x')) + ',' + org + ',' + str(pro_map.name) + ',Overwriting SD File,' + \
                         str(last) + '\n'
                output_file.write(output)
            except (NameError, TypeError) as e:
                print("*************  2  ***************")
                logger.info('Item is not published...')
                print('Item is not published...')
                logger_key = 1

                # Add item as service definition
                sc = datetime.now()  # Current Datetime
                try:
                    sdItem = gis.content.add({'title': sd_fs_name}, data=sd, folder=agol_folder)
                    logger.info('Uploading new Service Definition...')
                    print('Uploading new Service Definition...')
                except ValueError as e:
                    logger.critical('Could not add service %s to Org' % sd_fs_name)
                    logger.critical('Make sure you are signed into ArcGIS Pro. Save password if closing.')
                last = datetime.now() - sc  # Difference in time
                # Write publishing time to output csv
                org = str(gis).split("@")[1].split("//")[1].split(".")[0]
                output1 = str(time.strftime('%X %x')) + ',' + org + ',' + str(pro_map.name) + ',Add New SD,' + str(
                    last) + \
                          '\n'
                output_file.write(output1)

        except IndexError as e:
            print("*************  3  ***************")
            logger.info('Item is not published...')
            print('Item is not published...')
            logger_key = 1

            # Add item as service definition
            sc = datetime.now()  # Current Datetime
            try:
                print("*************  4  ***************")
                sdItem = gis.content.add({'title': sd_fs_name}, data=sd, folder=agol_folder)
                logger.info('Uploading new Service Definition...')
                print('Uploading new Service Definition...')
            except ValueError as e:
                logger.critical('Could not add service %s to Org' % sd_fs_name)
                logger.critical('Make sure you are signed into ArcGIS Pro. Save password if closing.')
            last = datetime.now() - sc  # Difference in time
            # Write publishing time to output csv
            org = str(gis).split("@")[1].split("//")[1].split(".")[0]
            output1 = str(time.strftime('%X %x')) + ',' + org + ',' + str(pro_map.name) + ',Add New SD,' + str(last) + \
                '\n'
            output_file.write(output1)

        if logger_key == 0:
            logger.info('Overwriting service: %s...' % pro_map.name)
            print('Overwriting service: %s...' % pro_map.name)
        else:
            logger.info('Publishing service: %s...' % pro_map.name)
            print('Publishing service: %s...' % pro_map.name)

        # Publish/Overwrite feature service and share according to sharing above.
        sc = datetime.now()  # Current Datetime
        publish_key = 0

        try:
            print("*************  5  ***************")
            fs = sdItem.publish(overwrite=True)
        except Exception as e:
            # Even if a timeout occurs, search and try and locate service. If found, the service published correctly.
            try:
                print("*************  6  ***************")
                fs = sdItem.publish(overwrite=True)
            except ConnectionResetError as e:
                # Even if a timeout occurs, search and try and locate service. If found, the service published correctly.
                fsItem = gis.content.search("{} AND owner:{}".format(sd_fs_name, user), item_type="Feature Service")
                if len(fsItem) >= 1:
                    publish_key = 0
                else:
                    logger.error('Could not publish service %s: %s' % (sd_fs_name, e))
                    publish_key = 1
                    print('**' + str(e) + '**')
            except Exception as e:
                # Even if a timeout occurs, search and try and locate service. If found, the service published correctly.
                fsItem = gis.content.search("{} AND owner:{}".format(sd_fs_name, user), item_type="Feature Service")
                if len(fsItem) >= 1:
                    publish_key = 0
                else:
                    logger.error('Could not publish service %s: %s' % (sd_fs_name, e))
                    publish_key = 1
                    print('**' + str(e) + '**')
            # fsItem = gis.content.search("{} AND owner:{}".format(sd_fs_name, user), item_type="Feature Service")
            # if len(fsItem) >= 1:
            #     publish_key = 0
            # else:
            #     logger.error('Could not publish service %s: %s' % (sd_fs_name, e))
            #     publish_key = 1
            #     print('**' + str(e) + '**')
        except ConnectionResetError as e:
            # Even if a timeout occurs, search and try and locate service. If found, the service published correctly.
            fsItem = gis.content.search("{} AND owner:{}".format(sd_fs_name, user), item_type="Feature Service")
            if len(fsItem) >= 1:
                publish_key = 0
            else:
                logger.error('Could not publish service %s: %s' % (sd_fs_name, e))
                publish_key = 1
                print('**' + str(e) + '**')

        last = datetime.now() - sc  # Difference in time

        if publish_key == 0:
            # Write publishing time to output csv
            org = str(gis).split("@")[1].split("//")[1].split(".")[0]
            output = str(time.strftime('%X %x')) + ',' + org + ',' + str(pro_map.name) + ',Publishing,' + str(last) + \
                     '\n'
            output_file.write(output)

            try:
                fs = gis.content.search("{} AND owner:{}".format(sd_fs_name, user), item_type="Feature Service")
                for i, value in enumerate(fs):
                    match = re.search(r'\"(.*)\"', str(value)).group(1)
                    if match == sd_fs_name:
                        n = i
                fs = fs[n]

                # Update Capabilities
                flc = arcgis.features.FeatureLayerCollection(fs.url, gis)
                flc.manager.update_definition(option_dict)
                logger.info('Added capabilities to service: %s' % option_dict)
                fs.share(org=shrOrg, everyone=shrEveryone, groups=shrGroups)
                logger.info('Sharing: Org: %s, Everyone: %s, Groups: %s' % (shrOrg, shrEveryone, shrGroups))
                print('Sharing: Org: %s, Everyone: %s, Groups: %s' % (shrOrg, shrEveryone, shrGroups))

                # Define metadata
                service_snippet = '{} in York County, PA.'.format(sd_fs_name)
                service_description = '{} in York County. Intended for illustration and demonstration purposes only.'.format(sd_fs_name)
                service_terms_of_use = 'FOR PUBLIC DISTRIBUTION. Layer should not be used at scales larger than 1:2400'
                service_credits = 'York County Planning Commission (YCPC)'
                service_tags = ['Open Data','{}'.format(open_cat)]

                # Create update dict
                item_properties = {'snippet' : service_snippet,
                                   'description' : service_description,
                                   'licenseInfo' : service_terms_of_use,
                                   'accessInformation' : service_credits,
                                   'tags' : service_tags}

                # If Statement on fs items
                # Update properties if AGOL item are empty ('' or null). If not, ignore update items.
                # This will essentially provide information to AGOL item if no information is provided.
                # This is my alternative because I should not get fs.properties working on my AGOL.
                # fs.properties mentions that there is no values for some reason
                #print(type(fs.properties))
                if fs.description == None or fs.tags == None or fs.licenseInfo == None:
                    print('AGOL Items are empty. Updating Item Properties for %s' % (sd_fs_name))
                    logger.info('AGOL Items are empty. Updating Item Properties for %s' % (sd_fs_name))
                    fs.update(item_properties)
##                elif fs.description == '' or fs.tags == '' or fs.licenseInfo == '':
##                    print('AGOL Items are empty. Updating Item Properties for %s' % (sd_fs_name))
##                    logger.info('AGOL Items are empty. Updating Item Properties for %s' % (sd_fs_name))
##                    fs.update(item_properties)
                else:
                    print("AGOL Item is not empty")
                    logger.info('AGOL Item is not empty for %s' % (sd_fs_name))

                logger.info('{}'.format(fs.tags))
                print('{}'.format(fs.tags))

##                #Added fs.properties logic that I could not get to work (works for Alex Brown but not here). But, wanted to include
##                #If you can get to work probably a better solution then above if statement
##                fs.url
##                print(type(fs.properties))
##
##                new_dict = {}
##                new_dict = fs.properties
##
##                new_dict
##
##                new_dict['copyrightText']
##
##                if new_dict['copyrightText'] == '':
##                    print('empty')
##                elif new_dict['copyrightText'] == null:
##                    print('empty')

            except Exception as e:
                logger.error('Could not share service: %s' % e)

            logger.info('-* Layer "%s" has been published. *-' % str(pro_map.name))
            print('-* Layer "%s" has been published. *-' % str(pro_map.name))

            n = None

    # Close output csv for logging time to publish.
    output_file.close()

    logger.info('---- Script: %s completed. ----' % scriptName)
    print('---- Script: %s completed. ----' % scriptName)

