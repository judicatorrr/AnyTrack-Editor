import os, sys, time, statistics, json, math
from pathlib import Path
os.environ['QT_QPA_PLATFORM']='offscreen'
sys.path.insert(0,sys.argv[1])
import numpy as np
from PySide6 import QtWidgets,QtCore
from fit_editor.main_window import MainWindow, TrackDocument
from fit_editor.model import Point, ActivityModel
app=QtWidgets.QApplication([])
w=MainWindow();w.map_widget._tile=lambda *a:None;w.resize(1500,1050);w.show()
n=30000
model=ActivityModel(Path('benchmark.gpx'),'gpx',[
 Point(t=float(i),lat=59+.04*math.sin(i/2500),lon=39+i*.000001,
       speed=6+math.sin(i/40),heart_rate=110+20*math.sin(i/70),
       cadence=80+10*math.sin(i/30),power=150+60*math.sin(i/80),
       distance=float(i*6),altitude=125+20*math.sin(i/500)) for i in range(n)],np.ones(n,dtype=bool))
w.tracks=[TrackDocument(model,'#50D890')];w.active_track_index=0
start=time.perf_counter();w.refresh_plots(reset_region=True,fit_map=True);app.processEvents()
results={'load_render_ms':(time.perf_counter()-start)*1000,'points':n}
w._selection_user_defined=True;w._set_selection_region(1000,9000);app.processEvents()
samples=[]
for i in range(12):
 start=time.perf_counter();w._set_selection_region(1000+i*20,9000+i*20);app.processEvents();samples.append((time.perf_counter()-start)*1000)
results['selection_median_ms']=statistics.median(samples)
p=w.graph_stack.panels['heart_rate'];w._activate_panel('heart_rate');samples=[]
for i in range(12):
 start=time.perf_counter();w._telemetry_mouse_moved((p.view.mapViewToScene(QtCore.QPointF(5000+i*50,110)),));app.processEvents();samples.append((time.perf_counter()-start)*1000)
results['hover_median_ms']=statistics.median(samples)
print(json.dumps(results));w.close()
