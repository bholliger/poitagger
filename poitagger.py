""" poi_tagger2 can read ARA-files and makes the georeference for points of interest

Usage:
    poitagger.py [<infolder>] [-r <rootdir>] [-w] [--remote-debugging-port=<port_number>]
    poitagger.py -h | --help
    poitagger.py --version

Arguments:
    <infolder>                              this is the folder for all in and output files 
Options:
    -r <rootdir>                            rootdirectory for the foldertree [default: None]
    -w                                      set windowposition to (x,y)=(0,0)
    --remote-debugging-port=<port_number>   set the Chromium Debugging Port for the QtWebEngine 
"""

from docopt import docopt
import warnings
warnings.filterwarnings("ignore", category=FutureWarning) # PyQtGraph has a FutureWarning: h5py: Conversion from float to np.floating is deprecated

from PyQt5 import QtCore,QtGui,uic, QtWidgets, QtPrintSupport
from PyQt5.QtWidgets import QApplication,QWidget,QMainWindow,QMessageBox,QTextEdit

import numpy as np

#wichtig fuer cxfreeze:
import numpy.core._methods 
import numpy.lib.format
import lxml._elementpath
import pyqtgraph.debug
import pyqtgraph.ThreadsafeTimer
import cytoolz
import codecs
#import encodings.codecs
#import skimage.io._plugins.freeimage_plugin


import sys
import os
import traceback
import shutil

import nested
import gpx
import utils2
import flightmeta

# Widgets
import save_as
import workflow

import pois

import info

import calib

import geoview
import dem
import properties
import imageview
#import dirtree
import treeview

paramreduce = nested.Nested(callback=nested.paramtodict,callback_pre=nested.pre_paramtodict,tupletype=list)
     
class Main(QMainWindow):
    curimgpath = QtCore.pyqtSignal(str)
    log = QtCore.pyqtSignal(str)
    saveimgdir = None
    dockwidgets = []
    
    
    def __init__(self, imgdir = None, rootdir = None,resetwindow = None):
        QMainWindow.__init__(self)
        #self.setIcon()
        #self.setWindowIcon(QtGui.QIcon('poitagger.png'))
        self.resetwindow = resetwindow
        self.msg = QMessageBox()
        self.settings = QtCore.QSettings("conf.ini", QtCore.QSettings.IniFormat)
        self.settings.setFallbacksEnabled(False) 
        rd = rootdir if rootdir is not None else str(self.settings.value('PATHS/rootdir'))
        id = imgdir if imgdir is not None else str(self.settings.value('PATHS/last'))
        
        self.imgdiff = 1 if imgdir is not None else int(self.settings.value('PATHS/lastimgid',0))
        startfilename = str(self.settings.value('PATHS/lastimgname'))
        
        self.saveDialog = save_as.SaveAsDialog(self)
        
        self.conf = properties.PropertyDialog("Einstellungen")
               
        #self.dir = treeview.TreeView() #dirtree.DirTree(rd,id)
        self.img = imageview.Img(self.conf,os.path.join(id,startfilename))
        self.flight = flightmeta.Flight(".poitagger.yml")
        #self.flight.load(id,".poitagger.yml")
        self.info = info.Info()
        self.calib = calib.Calib()
        self.dem = dem.Dem()
        self.wf = workflow.Araloader()
        
        self.pois = pois.Pois(self.conf)
        
        self.geomain = geoview.GeoWidget(self)
        
        self.treemain = treeview.TreeWidget(self)
        self.treemain.setRoot(rd)
        self.treeview = self.treemain.view
        self.treemodel = self.treeview.model
        self.treemodel.metafilename = ".poitagger.yml"
        self.loadUI()
        
        
       # self.pois.load(self.flightmeta.pois,id) 
        #self.pois.load_folder(self.dir.imgdir)
        
        self.shortcuts()
        self.connections()
        self.treemain.view.setFocus()
        
    def loadUI(self):
        uic.loadUi('ui/poitagger.ui',self)
        self.setCentralWidget(self.img.w)
        
        self.img.appendButtonsToToolBar(self.toolBar)
        
        self.flightmain = flightmeta.FlightWidget(self)
        self.flightmain.setMeta(self.flight)
        
        self.Console = QTextEdit(self.ConsoleDockWidget)
        
        self.leftVL.addWidget(self.img.proc.viewCtrlUI)
        self.rightVL.addWidget(self.img.proc.detectionUI)
        
        self.setDockWidget(self.CalibDockWidget,        'GUI/CalibDock',        self.calib)
        self.setDockWidget(self.DebugDockWidget,        'GUI/DebugDock')
        self.setDockWidget(self.WorkflowDockWidget,     'GUI/WorkflowDock')
        self.setDockWidget(self.ViewControlDockWidget,  'GUI/ViewControlDock')
        self.setDockWidget(self.DEMDockWidget,          'GUI/DEMDock',          self.dem)
        self.setDockWidget(self.ConsoleDockWidget,      'GUI/ConsoleDock',      self.Console)
        self.setDockWidget(self.PoisDockWidget,         'GUI/PoisDock',         self.pois)
        self.setDockWidget(self.GeoViewDockWidget,      'GUI/GeoViewDock',      self.geomain)
        self.setDockWidget(self.PixeltempDockWidget,    'GUI/PixeltempDock',    self.img.temp)
        self.setDockWidget(self.InfoDockWidget,         'GUI/InfoDock',         self.info.t)
        self.setDockWidget(self.FMInfoDockWidget,       'GUI/FMInfoDock',       self.flightmain) #fminfo
        self.setDockWidget(self.VerzeichnisDockWidget,  'GUI/VerzeichnisDock',  self.treemain)#.tree
        
        self.DebugVL.addWidget(self.img.wdebug)
        self.verticalLayout.addWidget(self.img.imgDebugUI)
        
        upperwidgets = [self.GeoViewDockWidget,self.CalibDockWidget, self.ViewControlDockWidget, self.DEMDockWidget]
        lowerwidgets = [self.ConsoleDockWidget, self.PoisDockWidget, self.DebugDockWidget, self.FMInfoDockWidget]
        [self.tabifyDockWidget( self.PixeltempDockWidget, w) for w in upperwidgets]
        [self.tabifyDockWidget( self.InfoDockWidget,w) for w in lowerwidgets]
        
        self.loadSettings(self.settings)
        
        self.show()
    
    def handlePrint(self):
        dialog = QtPrintSupport.QPrintDialog()
        if dialog.exec_() == QtWidgets.QDialog.Accepted:
            self.handlePaintRequest(dialog.printer())
        
    def handlePreview(self):
        dialog = QtPrintSupport.QPrintPreviewDialog()
        dialog.paintRequested.connect(self.handlePaintRequest)
        dialog.exec_()

    def handlePaintRequest(self, printer):
        painter = QtGui.QPainter()
        painter.begin(printer)
        painter.setPen(QtGui.QPen(QtGui.QColor(0, 0, 0)))
        
        self.geomain.view.render(painter,painter.deviceTransform().map(QtCore.QPoint(0,45)))   #painter.deviceTransform().map(QtCore.QPoint(0,45))
        
        font = QtGui.QFont("times", 12)
        painter.setFont(font)
        fm = QtGui.QFontMetrics(font)
        text = "Flug: " + self.treemain.view.imgdir
        pixelsWidth = fm.width(text)
        pixelsHeight = fm.height()
        painter.drawText(20, 20, pixelsWidth, pixelsHeight, QtCore.Qt.AlignLeft, text)
        
        painter.end()
        
    def setDockWidget(self,dockwidget,settingsprefix,widget=None):
        if not widget == None:
            dockwidget.setWidget(widget) 
                
        self.menuAnsicht.addAction(dockwidget.toggleViewAction())
        self.dockwidgets.append((dockwidget,settingsprefix))
        
    def connections(self):
        self.sdcard.clicked.connect(lambda: self.wf.readSDCard(self.saveDialog,self.settings,self.SDCard_leeren.checkState(),self.nurFlugBilder.checkState()))
        
        self.actionSD_Karte_einlesen.triggered.connect(lambda: self.wf.readSDCard(self.settings,self.SDCard_leeren.checkState(),self.nurFlugBilder.checkState()))
        #self.actionAra_korrigieren.triggered.connect(lambda: self.wf.readFolder(str(self.dir.treeitem.fileInfo(self.dir.tree.currentIndex()).absoluteFilePath())))
        self.actionAra_korrigieren.triggered.connect(lambda: self.wf.readFolder(self.treemain.view.current_path()))
        self.actionSave_poi_gpx.triggered.connect(self.pois.save_gpx)
        self.actionJpg_export.triggered.connect(self.img.save_jpg)
        self.actionPng_export.triggered.connect(self.img.save_png)
        self.actionConvert_folder_to_jpg.triggered.connect(lambda: self.wf.convertFolderJpg(self.treemain.view.current_path()))
        self.actionCreate_subimages.triggered.connect(lambda: self.wf.createSubimages(self.treemain.view.current_path()))
        self.actionGoogleMaps.triggered.connect(self.loadGoogleMaps)
        self.actionGpx_to_gps.triggered.connect(self.gpx_to_gps)
        
        self.actionEinstellungen.triggered.connect(self.conf.openPropDialog)
        
        self.info.position.connect(self.geomain.view.moveUav)
        #self.geomain.actionUAV_position.triggered.connect(lambda: self.geomain.view.panMap(self.img.ara.header["gps"]["latitude"],self.img.ara.header["gps"]["longitude"]))
        self.geomain.actionFitMap.triggered.connect(lambda: self.geomain.view.fitBounds(paramreduce.load(self.flight.p.child("general").child("bounding").getValues())))
        
        self.wf.progress.connect(self.AraLoaderProgressBar.setValue)
        self.log.connect(self.Console.append)
        self.wf.log.connect(self.Console.append)
        self.wf.critical.connect(lambda txt : QtGui.QMessageBox.critical(self, "SD-Karte einlesen",txt))
        self.wf.info.connect(lambda txt : QtGui.QMessageBox.information(self, "SD-Karte einlesen",txt))
        
        self.pois.log.connect(self.Console.append)
        self.treemain.view.log.connect(self.Console.append)
        self.img.log.connect(self.Console.append)
        self.img.proc.log.connect(self.Console.append)
                
        self.actionDrucken.triggered.connect(self.handlePrint)
        self.actionDruckansicht.triggered.connect(self.handlePreview)
        
        self.escAction.triggered.connect(self.close)
        
        self.pois.liste.connect(self.img.paintPois) #selektierter Poi
        
        # aRA UEBERSCHREIBEN MIT EIGENEN wERTEN
        self.calib.conf.connect(lambda conf: self.wf.readFolder(self.treemain.view.imgdir,conf))
        
       # self.flightmeta.importimages.connect(self.wf.readFolder)
        
        [self.treemain.view.imgPathChanged.connect(c) for c in [self.img.loadImg,self.setWindowTitle]]
        self.treemain.view.imgDirChanged.connect(lambda imgdir: self.flight.load(imgdir))
        
        self.flight.uavpath.connect(self.geomain.view.setUavPath)
        self.flight.pois.connect(self.geomain.view.loadpois)
        self.flight.pois.connect(lambda pois: self.pois.load(pois, self.flight.path))
        #self.flight.meta.pois_changed.connect(self.geomain.view.loadpois)
        #self.flight.meta.pois_changed.connect(lambda: self.pois.load(self.flightmeta.pois, self.flightmeta.path))
                                            
        #[self.dir.imgDirChanged.connect(c) for c in [self.pois.load_folder, lambda : self.geoview.loadpois(self.flightmeta.pois),lambda : self.geoview.setUavPath(os.path.join(self.dir.imgdir,"uavpositions.gpx"))]]#self.geoview.setAllPois(os.path.join(self.dir.imgdir,"pois.gpx"))
        #]] #,self.geoview.prepareLoadGpx
        self.img.loaded.connect(lambda: self.fill_values(self.img.ara))
        self.treemain.view.imgDirChanged.connect(lambda: self.img.proc.setdirlist(self.treemain.view.aralist))
        self.treemain.view.rootDirChanged.connect(lambda rootdir: self.settings.setValue('PATHS/rootdir', rootdir))
        
        self.img.highlighting.connect(self.treemain.vb.imagename.setStyleSheet)
        #self.info.uncalibrated.connect(self.dir.viewbuttonsUI.imagename.setStyleSheet)
        
        self.img.sigPixel.connect(self.pois.pos)
        self.img.sigMouseMode.connect(self.focusDockWidget)
        
    def gpx_to_gps(self):
        #print "GPX auf GPS uebertragen", 
        self.pois.save()
        self.flight.save()
        
        
        #print("imgdir",self.dir.imgdir)
        poisfilename = "pois.gpx" #os.path.join(self.dir.imgdir,"pois.gpx")
        if os.path.exists("pois.gpx"):
            os.remove("pois.gpx")
        self.gpxgen = gpx.GpxGenerator("pois.gpx")
        try:
            for i in self.pois.poilist:
                self.gpxgen.add_wpt(str(i[5]),str(i[6]),str(i[7]),self.img.ara.header["gps"]["dateTtime"],str(i[2]),"poi")
            self.gpxgen.save(poisfilename,False)
        except:
            traceback.print_exc()#"save gpx failed"
        
        self.exportgpx(poisfilename)#,self.conf)
        #cmd = 'gpsbabel -w -r -t -i gpx,suppresswhite=0,logpoint=0,humminbirdextensions=0,garminextensions=0 -f "' + poisfilename + '" -o garmin,snwhite=0,get_posn=0,power_off=0,erase_t=0,resettime=0 -F usb:'
        #print cmd
        #os.system(cmd)
    
    
    def exportgpx(self,gpxfile):#, conf):
        if str(self.settings.value('GPS-DEVICE/exportType')) == "serial":# conf.garminserial_rB.isChecked():
            cmd = 'gpsbabel -w -r -t -i gpx,suppresswhite=0,logpoint=0,humminbirdextensions=0,garminextensions=0 -f "' + gpxfile + '" -o garmin,snwhite=0,get_posn=0,power_off=0,erase_t=0,resettime=0 -F usb:'
            ret = os.system(cmd)
            if ret == 0: 
                QtGui.QMessageBox.information(self, "Gps-Datenuebertragung ","Die GPS-Datenuebertragung war erfolgreich! Die Wegpunkte wurden ueber das Garmin-Serial/USB-Protokoll uebertragen"); 
                #msg.setWindowIcon(QtGui.QIcon('icons/okay.png'))
            else:
                QtGui.QMessageBox.critical(self, "Gps-Datenuebertragung fehlgeschlagen!","ein altes Garmin Geraet wurde nicht gefunden (bei einem neueren GPS-Geraet muss unter Einstellungen/allgemein/GPS-Device MassStorage Device anstatt Garmin Serial/USB ausgewaehlt werden)!"); 
                #msg.setWindowIcon(QtGui.QIcon('icons/failed.png'))
                
        elif  str(self.settings.value('GPS-DEVICE/exportType')) == "massStorage":# conf.massStorage_rB.isChecked():
            if str(self.settings.value('GPS-DEVICE/detectMode')) == "name": #conf.detectName_rB.isChecked():
                drive = utils2.getSDCardPath(str(self.settings.value('GPS-DEVICE/harddrive'))) #str(conf.name_LE.text()))
                if drive==False:
                    QtGui.QMessageBox.critical(self, "Gps-Datenuebertragung fehlgeschlagen!","GPS-Geraet nicht gefunden (Ein Geraet mit dem Namen  %s existiert nicht)!"%str(conf.name_LE.text())); 
                    
                    
            elif str(self.settings.value('GPS-DEVICE/detectMode'))== "fixedfolder": #conf.fixedFolder_rB.isChecked():
                drive = str(self.settings.value('GPS-DEVICE/harddrive')) #str(conf.harddrive_LE.text())
            else:
                QtGui.QMessageBox.critical(self, "Info0","kein Detektionsmodus gewaehlt! (unter Einstellungen/GPS-Device)"); 
            
            if not drive==False:
                outdir = os.path.join(drive,str(self.settings.value('GPS-DEVICE/gpxfolder')))    #conf.folder_LE.text()
            
           # print("outdir", outdir)
                if os.path.isdir(outdir):
                   # print("copy", gpxfile,"->", outdir)
                    gpxfilename = "pois.gpx"
                    outpath = os.path.join(outdir,gpxfilename)
                    shutil.copyfile(gpxfile, outpath)
                    QtGui.QMessageBox.information(self, "Gps-Datenuebertragung ","Die GPS-Datenuebertragung war erfolgreich! Die Wegpunkte wurden hierher kopiert: %s "%outpath); 
                    
                
                else:
                    QtGui.QMessageBox.critical(self, "Gps-Datenuebertragung fehlgeschlagen!","GPS-Geraet nicht gefunden (Das angegebene Verzeichnis %s existiert nicht)!"%outdir); 
            else:
                    QtGui.QMessageBox.critical(self, "Gps-Datenuebertragung fehlgeschlagen!","GPS-Geraet nicht gefunden (Das Laufwerk des GPS-Geraetes wurde nicht erkannt)!"); 
                
        else:
            QtGui.QMessageBox.critical(self, "Info2","kein export device typ gewaehlt (unter Einstellungen/GPS-Device)"); 
                    
            
    
    def focusDockWidget(self,mousemode):
        if mousemode == "temp":
            self.PixeltempDockWidget.raise_()
        if mousemode == "poi":
           self.PoisDockWidget.raise_()
           
        
    def loadSettings(self, s):
        [self.setTopDockWidget(w, s.value(v+"Focus")=="true") for w,v in self.dockwidgets]
        [w.setVisible(s.value(v+"Visible")=="true") for w,v in self.dockwidgets]
        size = QtCore.QSize(s.value('GUI/size'))
        pos = QtCore.QPoint(s.value('GUI/pos'))
        screen = app.primaryScreen()  
        if self.resetwindow:
            self.resize(800,600)
            self.move(0,0)
        else:
            curscreen = screenAt(pos)
            if not curscreen:
                pos = QtCore.QPoint(0,0)
                curscreen = screenAt(pos)
            size = size.boundedTo(curscreen.virtualSize())
            self.resize(size)
            self.move(pos)
        
        
        self.img.proc.viewCtrlUI.CVfliphorCheckBox.setChecked(s.value('VIEW/fliphor')=="true")
        self.img.proc.viewCtrlUI.CVflipverCheckBox.setChecked(s.value('VIEW/flipver')=="true")
        
        self.pois.loadSettings(self.settings)
        #self.poisproperties.loadSettings(self.settings)
        
    def writeSettings(self,s):
        s.setValue('PATHS/rootdir', self.treemain.view.rootdir)
        s.setValue('PATHS/last', self.treemain.view.imgdir)
        if len(self.treemain.view.aralist)>0:
            s.setValue('PATHS/lastimgid', self.treemain.view.aralist[0]["id"])
            s.setValue('PATHS/lastimgname', self.treemain.view.aralist[0]["filename"])
        s.setValue('GUI/size', self.size())
        s.setValue('GUI/pos', self.pos())
        #s.setValue('GUI/PoisDocksize',self.pois.size())
        
        [s.setValue(v+"Visible",w.isVisible()) for w,v in self.dockwidgets]
        [s.setValue(v+"Focus",self.isTopDockWidget(w)) for w,v in self.dockwidgets]
        
        s.setValue('VIEW/fliphor',self.img.proc.viewCtrlUI.CVfliphorCheckBox.isChecked())
        s.setValue('VIEW/flipver',self.img.proc.viewCtrlUI.CVflipverCheckBox.isChecked())
        
        self.pois.writeSettings()
        
        
    def shortcuts(self):
        self.escAction = QtGui.QAction('escape', self)
        self.clearAction = QtGui.QAction('clear', self)
        self.createKeyCtrl(self.escAction, QtCore.Qt.Key_Escape)
        self.createKeyCtrl(self.clearAction, QtCore.Qt.Key_C)
        
    def createKeyCtrl(self,actionName, key):
        actionName.setShortcut(QtGui.QKeySequence(key))
        self.addAction(actionName)
    
    def loadGoogleMaps(self):
        url = QtCore.QUrl("https://www.google.de/maps/place//@%s,%s,17z/data=!3m1!1e3!4m2!3m1!1s0x0:0x0" % (self.img.ara.header["gps"]["latitude"],self.img.ara.header["gps"]["longitude"]))
        QtGui.QDesktopServices.openUrl(url)
        
    def fill_values(self,ara):
        self.info.load_data(ara.header)
        self.calib.load_data(ara.header)
        self.pois.load_data(ara,self.treemain.view.imgname,self.calib)#self.img.araalt,
        #self.geomain.view.load_filedata(ara.header)
        
    def isTopDockWidget(self,widget):
        if widget.visibleRegion().isEmpty():
            return False
        else:
            return True
    
    def setTopDockWidget(self,widget,boolvar):
        if boolvar:
            widget.raise_()
   
    def closeEvent(self, e=None):
        self.settings.sync()
        #print(self.settings.value('POIS/color'))
        self.writeSettings(self.settings)
        #self.flightmeta.change_pois(self.pois.poisxml)
        self.flight.save()#self.flightmeta.path)
        if e: e.accept()


def screenAt(*pos):
    screens = app.screens()
    for s in screens:
        srect = s.availableGeometry()
        if srect.contains(*pos):
            return s
    return None
    

if __name__ == "__main__":
    arg = docopt(__doc__, version='poitagger 0.1')
    app = QtGui.QApplication(sys.argv)
    
    if os.name == "nt":
       import ctypes
       myappid = 'dlr.wildretter.poitagger.1' 
       ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    app_icon = QtGui.QIcon()
    app_icon.addFile('ui/icons/poitagger/16x16_.png', QtCore.QSize(16,16))
    app_icon.addFile('ui/icons/poitagger/24x24_.png', QtCore.QSize(24,24))
    app_icon.addFile('ui/icons/poitagger/32x32_.png', QtCore.QSize(32,32))
    app_icon.addFile('ui/icons/poitagger/48x48_.png', QtCore.QSize(48,48))
    app_icon.addFile('ui/icons/poitagger/256x256_.png', QtCore.QSize(256,256))
    
    imgdir = None
    rootdir = None
    if arg["<infolder>"] is not None:
        if os.path.isfile(arg["<infolder>"]):
            imgdir, file = os.path.split(arg["<infolder>"])
        if os.path.isdir(arg["<infolder>"]):
            imgdir = arg["<infolder>"]
    if arg["-r"] is not None:
        if os.path.isdir(arg["-r"]):
            rootdir = arg["-r"]
    window=Main(imgdir,rootdir,arg["-w"])
    
    
    window.setWindowIcon(app_icon)
    window.show()
    sys.exit(app.exec_())