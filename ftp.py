import timeit
import os
from glob import glob
import numpy as np
import sys
from skimage import io
import psutil
from joblib import Parallel, delayed
from tqdm import tqdm
import scipy.signal
import math

def analyze_image_stack (path, vox_dim, matrix=None, air=None, res=None, z_corr=None):
    start = timeit.default_timer()
    np.set_printoptions(threshold=sys.maxsize, linewidth=200)
    path0 = os.getcwd ()
    path_img = ("".join ([path, "\\img"]))
    path_mask = ("".join ([path, "\\msk"]))
    path_store = ("".join ([path, "\\Minima_Analysis"]))
    os.chdir (path_mask)
    mask_stack = sorted (glob("*.tif"))
    if len(mask_stack)==0:
        raise ValueError("No TIF files found in the folder msk")
    os.chdir (path_img)
    img_stack = sorted (glob("*.tif"))
    for i in range (0, len(mask_stack), 1):
        mask_stack[i] = ("".join ([path_mask, "\\", mask_stack[i]]))
    if len(mask_stack)==0:
        raise ValueError("No TIF files found in the folder img")
    print ("Image shape is\tz: {}\ty: {}\tx: {}\n".format(len(img_stack), io.imread(img_stack[0], plugin='pil').shape[0], io.imread(img_stack[0], plugin='pil').shape[1]))
    os.chdir(path)
    if os.path.exists (path_store):
        if len(os.listdir(path_store))>0:
            for f in os.listdir(path_store):
                os.remove(os.path.join(path_store, f))
    else:
        os.makedirs ("Minima_Analysis")
    img3D = []
    img_mask3D = []
    os.chdir (path_img)
    modules = ['imageio','pil','tifffile','matplotlib']
    module_i=[]
    module_m=[]
    for n, i in enumerate(modules):
        if np.array(io.imread(img_stack[0], plugin=i)).ndim==2 and len(module_i)==0:
            module_i = modules[n]
        if np.array(io.imread(mask_stack[0], plugin=i)).ndim==2 and len(module_m)==0:
            module_m = modules[n]
    if not module_i or not module_m:
        raise ValueError("Cannot open mask properly with skimage.io")
    for i in zip (img_stack, mask_stack):
        img3D.append (io.imread (i[0], plugin=module_i))
        img_mask3D.append (io.imread (i[1], plugin=module_m))
    del img_stack; del mask_stack
    img3D = np.array (img3D, copy=False)
    img_mask3D = np.array (img_mask3D, copy=False, dtype="uint8")
    img3D[:,0,:] = 0; img3D[:,-1,:] = 0; img3D[:,:,0] = 0; img3D[:,:,-1] = 0
    img3D_rot =  np.rot90 (img3D, k=1, axes=(2,1))
    img3D_rot = img3D_rot[:,:,::-1]
    # Analysis minima
    arr_minH3D, dataH = analyze_profile (img3D, img_mask3D, matrix, air, res, md='h')
    img_mask3D_rot = img_mask3D.copy()
    img_mask3D_rot[np.where(arr_minH3D>0)] = 0
    img_mask3D_rot =  np.rot90 (img_mask3D_rot, k=1, axes=(2,1))
    img_mask3D_rot = img_mask3D_rot[:,:,::-1]
    arr_minV3D_rot, dataV = analyze_profile (img3D_rot, img_mask3D_rot, matrix, air, res, md='v')
    del img3D; del img_mask3D; del img3D_rot; del img_mask3D_rot
    # H, V, and HV minima images
    os.chdir (path_store)
    arr_minH3D = np.array (arr_minH3D, dtype="uint8", copy=False)
    arr_minV3D_rot = np.array (arr_minV3D_rot, dtype="uint8", copy=False)
    arr_minV3D_rot = arr_minV3D_rot[:,:,::-1]
    arr_minV3D_rot = np.rot90 (arr_minV3D_rot, k=1, axes=(-2,-1))
    arr_minHV3D = np.add (arr_minH3D, arr_minV3D_rot, dtype="uint8")
    del arr_minV3D_rot; del arr_minH3D
    # Pad HV_min and HV_rec with zeroes
    dataH = np.array(dataH, copy=False)
    dataV = np.array(dataV, copy=False)
    eg_eg = vox_dim//2
    dataH[:,:3]=dataH[:,:3]+eg_eg; dataH = list(dataH)
    dataV[:,:3]=dataV[:,:3]+eg_eg; dataV = list(dataV)
    arr_minHV3D = np.pad(arr_minHV3D, ((eg_eg,eg_eg), (eg_eg,eg_eg), (eg_eg, eg_eg)), mode='constant', constant_values=0)
    # Orientation Analysis
    elapsed_1 = timeit.default_timer(); print ("Minima analysis took {}s".format(round(timeit.default_timer() - start), 2))
    print ("\nCalculating orientations on {} points...".format(len(dataH)+len(dataV)))  
    if psutil.virtual_memory()[2]>85: raise ValueError("Low memory. {}% used.".format(psutil.virtual_memory()[2]))
    half_dim = vox_dim//2
    rs = Parallel(n_jobs=-1)(delayed(ftp_orientation_cpu)(arr_minHV3D, dataH[n], vox_dim, half_dim, H=True, core=True, z_c=z_corr) for n in tqdm(range(len(dataH)), desc='Orientation analysis', ncols=100)) #CPU1
    dataH = Parallel(n_jobs=-1)(delayed(np.insert)(dataH[n], 3, rs[n]) for n in tqdm(range(len(dataH)), desc='Inserting orientation data', ncols=100)); del rs #CPU2
    elapsed_2 = timeit.default_timer(); print ("{}\tH points are done....it took {}s".format(len(dataH), round(elapsed_2 - elapsed_1), 2)) #Stops script if RAM is full
    if psutil.virtual_memory()[2]>85: raise ValueError("Low memory. {}% used.".format(psutil.virtual_memory()[2]))
    rs = Parallel(n_jobs=-1)(delayed(ftp_orientation_cpu)(arr_minHV3D, dataV[n], vox_dim, half_dim, H=False, core=True, z_c=z_corr) for n in tqdm(range(len(dataV)), desc='Orientation analysis', ncols=100)) #CPU1
    dataV = Parallel(n_jobs=-1)(delayed(np.insert)(dataV[n][3:], 0, ([dataV[n][0], dataV[n][2], dataV[n][1], rs[n][0], rs[n][1]])) for n in tqdm(range(len(dataV)), desc='Inserting orientation data', ncols=100)); del rs  #CPU2
    elapsed_3 = timeit.default_timer(); print ("{}\tV points are done...it took {}s".format(len(dataV), round(elapsed_3 - elapsed_2), 2))
    arr_minHV3D = arr_minHV3D[eg_eg:-eg_eg,eg_eg:-eg_eg,eg_eg:-eg_eg]
    io.imsave ("img_3dHV.tif", arr_minHV3D)
    del arr_minHV3D
    print ("\nSaving data...")
    data_format = " z,   y,   x,  da,  dd, val, res,FWHM,  PH,  MA"
    dataH = np.array (dataH, copy=False)
    dataH[:,:3]=dataH[:,:3]-eg_eg
    np.savetxt ("mfps_H.txt", dataH, fmt='%04d', delimiter=',', header=data_format)
    dataV = np.array (sorted (dataV, key=lambda x: (x[0], x[1], x[2])), copy=False)
    dataV[:,:3]=dataV[:,:3]-eg_eg
    np.savetxt ("mfps_V.txt", dataV, fmt='%04d', delimiter=',', header=data_format)
    dataHV = np.concatenate ((dataH[:,:5], dataV[:,:5]), axis=0)
    dataHV.view("i,i,i,i,i").sort(order=['f0','f1','f2'], axis=0)
    np.savetxt ("mfps_HV.txt", dataHV, fmt='%04d', delimiter=',', header=data_format[:22])
    print ("\nData H shape:\t{}\nData V shape:\t{}\nData H&V shape:\t{}\n".format(dataH.shape, dataV.shape, dataHV.shape))
    print ("\nThe function took {} seconds.\nEND".format(round(timeit.default_timer() - start),2))
    del dataH; del dataV; del dataHV
    os.chdir (path0)

def analyze_profile (arr3d, msk, mtrx, air, rs, md=None):
    """Analyze a 1D profile and return:
    - a binary array with ones at valleys positions;
    - an array that contains for each valley these measurements: valley_index, value_valley, LSF, FWHM, PH, MA"""
    arr_min3D = np.zeros((arr3d.shape))
    data = []
    for n in tqdm(range(0, len(arr3d), 1), desc='Traverse Analysis', ncols=100):
        if psutil.virtual_memory()[2]>90:
            raise ValueError("Low memory. {}% used.".format(psutil.virtual_memory()[2]))
        for m in range(0, len(arr3d[n])-1, 1):
            if np.count_nonzero(msk[n, m, :])>0:
                arr = arr3d[n, m, :].copy()
                msk_indx = np.nonzero (msk[n, m, :])
                peaks, _ = scipy.signal.find_peaks (arr)
                arr_v = -1*arr
                height_min = np.amin(arr_v[msk_indx])
                height_max = (np.amax(arr_v[msk_indx]) if np.amax(arr_v[msk_indx])<0 else -1)
                valleys, _ = scipy.signal.find_peaks (arr_v, height=(height_min, height_max))
                valleys = np.intersect1d (valleys, msk_indx, assume_unique=True)
                del arr_v; del msk_indx
                true_valleys = []
                res = []
                PH = []
                FWHM = []
                MA = []
                valleys = valleys[valleys<mtrx]
                fwhm = ((mtrx-air)/2)+air
                if valleys.size > 0 and peaks.size > 0:
                    for i in valleys:                
                        idx = np.searchsorted (peaks, i)
                        edge_sx = peaks[idx-1]
                        edge_dx = peaks[idx]
                        if arr[edge_sx-1]==0 or arr[edge_dx+1]==0 or arr[i-1]==0 or arr[i+1]==0:
                            pass
                        else:
                            true_valleys.append(i)
                            size = ((edge_dx-edge_sx)/2)*0.8
                            if size>rs and arr[i]<fwhm:
                                FWHM_sx_edge = i-closest_indx(np.flip(arr[edge_sx:i+1]), fwhm)
                                FWHM_dx_edge = i+closest_indx(arr[i:edge_dx+1], fwhm)
                                if arr[FWHM_dx_edge]<fwhm:
                                    if arr[FWHM_dx_edge+1] == arr[FWHM_dx_edge]:
                                        while arr[FWHM_dx_edge+1] == arr[FWHM_dx_edge]:
                                            FWHM_dx_edge = FWHM_dx_edge+1
                                    a = float(arr[FWHM_dx_edge+1] - arr[FWHM_dx_edge])
                                    a_f = float(fwhm - arr[FWHM_dx_edge])
                                    perc = (a_f/a)
                                    FWHM_dx_edge = round(FWHM_dx_edge + perc, 1)
                                else:
                                    a = float(arr[FWHM_dx_edge] - arr[FWHM_dx_edge-1])
                                    a_f = float(arr[FWHM_dx_edge] - fwhm)
                                    perc = (a_f/a)
                                    FWHM_dx_edge = round(FWHM_dx_edge - perc, 1)
                                if arr[FWHM_sx_edge]<fwhm:
                                    if arr[FWHM_sx_edge-1] == arr[FWHM_sx_edge]:
                                        while arr[FWHM_sx_edge-1] == arr[FWHM_sx_edge]:
                                            FWHM_sx_edge = FWHM_sx_edge-1
                                    a = float(arr[FWHM_sx_edge-1] - arr[FWHM_sx_edge])
                                    a_f = float(fwhm - arr[FWHM_sx_edge])
                                    perc = (a_f/a)
                                    FWHM_sx_edge = round(FWHM_sx_edge + perc, 1)
                                else:
                                    a = float(arr[FWHM_sx_edge] - arr[FWHM_sx_edge+1])
                                    a_f = float(arr[FWHM_sx_edge] - fwhm)
                                    perc = (a_f/a)
                                    FWHM_sx_edge = round(FWHM_sx_edge - perc, 1)
                            else:
                                FWHM_sx_edge = 0.0
                                FWHM_dx_edge = 0.0
                                pass
                            FWHM.append ((FWHM_dx_edge - FWHM_sx_edge)*10) #FWHM*10 (px)
                            res.append (size)
                            pk_aver = (float(arr[edge_sx]+arr[edge_dx])/2)
                            pk_aver = pk_aver if pk_aver>air else mtrx
                            edg_edg_MA = pk_aver - arr[edge_sx:edge_dx+1]
                            edg_edg_MA = edg_edg_MA[edg_edg_MA>0]
                            MA.append (np.sum(edg_edg_MA/(pk_aver-air))*10) #Relative peaks MA*10 (dimensionless)
                            ph = (float(mtrx-arr[i])/float(mtrx-air))*10
                            PH.append(round(ph, 1)) #PH*10 (dimensionless)
                if true_valleys:
                    value = np.take (arr3d[n, m, :], true_valleys)
                    arr_min3D[n, m, true_valleys] = 255
                    z = [n]*len(true_valleys)
                    y = [m]*len(true_valleys)
                    data.append (zip (z, y, true_valleys, value, res, FWHM, PH, MA))
    flatten = [k for i in data for k in i]
    flatten = np.array(flatten); print ('')
    return arr_min3D, flatten

def closest_indx (x1, x2):
    """Return from the indexes in x1, the closest to x2"""
    np.seterr(all='ignore')
    abs_=[]
    for i in x1:
        abs_.append(abs(i-x2))
    indx = abs_.index(min(abs_))
    return indx

def ftp_orientation_cpu(img, dt, d, h, H=True, core=True, z_c=None):
    """It measure the orientation of the plane that best fits the FTPs"""
    np.seterr(invalid='ignore');
    Z=dt[0]
    Y = dt[1] if H is True else dt[2]
    X = dt[2] if H is True else dt[1]
    arr = img[int(Z)-h:int(Z)+(d-h), int(Y)-h:int(Y)+(d-h), int(X)-h:int(X)+(d-h)].copy()
    orient=[]
    if np.count_nonzero(arr)<3:
        orient.append([-1.,-1.])
        pass
    else:
        if core is True:
            arr = np.rot90(arr, axes=(0,1))
            indx = np.nonzero(arr)
        else:
            indx = np.nonzero(arr)
        z = indx[0]
        y = indx[1]
        x = indx[2]
        if z_c is not None and core is True:
            y=y*z_c
        elif z_c is not None and core is not True:
            z=z*z_c
        x = x - np.mean(x)
        y = y - np.mean(y)
        z = z - np.mean (z)
        evals, evecs = np.linalg.eig(np.cov([x, y, z]))
        sort_indices = np.argsort(evals)[::-1]
        x_v3, y_v3, z_v3 = evecs[:, sort_indices[2]]
        north = np.asarray ([0,0,1])
        zenith = np.asarray ([0,-1,0])
        normal = np.asarray ([x_v3, y_v3, z_v3])
        normal = normal*(-1.0 if normal[1]>=0 else 1.0)
        normalh = np.asarray ([normal[0], 0.0, normal[2]])
        v1_u = normal/np.linalg.norm(normal)
        v2_u = zenith/np.linalg.norm(zenith)
        v3_u = normalh/np.linalg.norm(normalh)
        v4_u = north/np.linalg.norm(north)
        da = round(np.degrees(np.arccos(np.clip(np.dot(v1_u, v2_u), -1.0, 1.0))),0)
        dd = round(np.degrees(np.arccos(np.clip(np.dot(v3_u, v4_u), -1.0, 1.0))),0)
        if normalh[0]<0 and dd<=180:
            dd = 360-dd
        elif normalh[0]>0 and dd>180:
            dd = 360-dd
        else:
            pass
        if math.isnan(da) or math.isnan(dd):
            orient.append([-1.,-1.])
        else:
            orient.append([da, dd])
    return orient[0]

path = (r"PutPathHere")
#vox_dim: size of the 3D local crop for orientation analysis
#matrix: mean matrix CT-value
#air: mean air CT-value
#res: FWHM value will only be measured for structures with an Edge Response (ER)>res and if the FTP is below the FWHM baseline value [((mtrx-air)/2)+air]
#z_corr: for cubic voxel is equal to 1 (put None in that case), for non cubic voxel (with x=y) is z/x
analyze_image_stack (path, vox_dim=11, matrix=255, air=0, res=1, z_corr=None)
