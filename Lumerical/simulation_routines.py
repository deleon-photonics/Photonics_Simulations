import simulation_objects as so
import lumapi as lp
import numpy as np
import os
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm
from scipy.signal import find_peaks
import pickle
import scipy.io
import math
from scipy.optimize import curve_fit
from scipy.constants import c
import random
import string


# Fit each peak with a Lorentzian or Gaussian function
def lorentzian(x, x0, gamma, A):
    return A * gamma**2 / ((x - x0)**2 + gamma**2)

def fit_Q(freqs, Esq):
    peaks,_ = find_peaks(Esq, height=0.05, distance=10)
    Q_factors = []
    res_wvls = []

    for peak in peaks:
        left_bound = max(0, peak - 20)
        right_bound = min(len(freqs) - 1, peak + 20)
        fit_freqs = freqs[left_bound:right_bound]
        fit_Esq = Esq[left_bound:right_bound]

        # Initial guess for fitting parameters
        x0_guess = freqs[peak]
        A_guess = max(fit_Esq)
        gamma_guess = (fit_freqs[-1] - fit_freqs[0]) / 4  # Initial guess for FWHM

        # Perform curve fitting
        popt, _ = curve_fit(lorentzian, fit_freqs, fit_Esq, p0=[x0_guess, gamma_guess, A_guess])
        # Extract parameters   
        x0_fit, gamma_fit, A_fit = popt

        # Calculate FWHM from gamma_fit (for Lorentzian, FWHM = 2 * gamma)
        fwhm = 2 * gamma_fit

        # Calculate Q-factor
        q_factor = x0_fit / fwhm
        Q_factors.append(q_factor)
        res_wvls.append(c / x0_fit)

    return Q_factors, res_wvls, peaks

def compute_fft(E, dt, pad_factor=1):
    N = len(E)
    N_padded = N*pad_factor
    E_padded = np.pad(E, (0, N_padded - N), mode='constant')  # Pad with zeros
    E_fft = np.fft.fft(E_padded)
    E_fft = np.fft.fftshift(E_fft)  # Shift zero frequency components to the center
    freqs = np.fft.fftfreq(N_padded, dt)
    freqs = np.fft.fftshift(freqs)  # Shift zero frequency components to the center

    return freqs, E_fft

#Microdisk resonances
def microdisk_resonances(disk_radius, disk_thickness, material_index, wavelength, wavelength_span,
                         sub_disk = 0, sub_disk_radius = 0):
    
    sim = lp.FDTD(hide=True)

    output_folder = "r_" + str(int(disk_radius*1e9)) + "nm_t_" + str(int(disk_thickness*1e9)) + "nm"
    FDTD_zmin_BC = "symmetric"
    if sub_disk == 1:
        subdisk = so.microdisk(thickness = disk_thickness/2 + wavelength,
                                z = -disk_thickness/2 - (disk_thickness/2 + wavelength)/2,
                                radius = sub_disk_radius, index = material_index,
                                name = "sub_disk")
        subdisk.add_to_sim(sim)
        FDTD_zmin_BC = "PML"
        output_folder = ("r_" + str(int(disk_radius*1e9)) + "nm_t_" + 
                         str(int(disk_thickness*1e9))  + "nm_U_" + 
                         str(int((disk_radius - sub_disk_radius)*1e9)) + "nm")
    
    os.makedirs(output_folder, exist_ok=True)

    sim.setglobalsource("wavelength start", wavelength - wavelength_span/2)
    sim.setglobalsource("wavelength stop", wavelength + wavelength_span/2)
    sim.setglobalmonitor("wavelength center", wavelength)
    sim.setglobalmonitor("wavelength span", 2*wavelength_span)

    disk = so.microdisk(thickness = disk_thickness, radius = disk_radius, index = material_index)
    disk.add_to_sim(sim)

    if disk_thickness == 0:
        dimension = '2D'
        dipole_angle = 90
    else:
        dimension = '3D'
        dipole_angle = 0
    fdtd = so.FDTD(xspan = disk_radius*2 + 2*wavelength, 
                   yspan = disk_radius*2 + 2*wavelength, 
                   zspan = disk_thickness + 2*wavelength, 
                   dimension = dimension, 
                   sim_time = 6e-12,
                   xmin_bc = 'symmetric',
                   ymin_bc = 'anti-symmetric',
                   zmin_bc = FDTD_zmin_BC,
                   mesh_accuracy = 3)
    fdtd.add_to_sim(sim)

    theta = 25
    for xi in [-1,0,1]:
        for yi in [-1,0,1]:
            x = np.cos(theta*np.pi/180)*disk_radius - 3*wavelength/32 + xi*wavelength/16
            y = np.sin(theta*np.pi/180)*disk_radius - 3*wavelength/32 + yi*wavelength/16
            dipole = so.dipole(x=x, y=y, z = 5e-9, wvl_start = wavelength - wavelength_span/2, wvl_stop = wavelength + wavelength_span/2, 
                               dipole_type = 'Magnetic Dipole', theta=dipole_angle, phi=dipole_angle)
            dipole.add_to_sim(sim)

    theta = 35
    x = np.cos(theta*np.pi/180)*(disk_radius - wavelength/8)
    y = np.sin(theta*np.pi/180)*(disk_radius - wavelength/8)
    time_monitor = so.time_monitor(x=x, y = y, z = 5e-9, start_time = 500e-15, min_sampling = 100)
    time_monitor.add_to_sim(sim)
    
    mesh = so.mesh(xspan = 2*disk_radius, yspan = 2*disk_radius)
    #mesh.add_to_sim(sim)

    if os.path.isfile('gui.fps'):
        os.remove('gui.fsp')
    sim.save('gui.fsp')
    
    try:
        sim.run()
        
        time_spectrum = sim.getresult(time_monitor.get_name(), 'E')#sim.getresult(time_monitor.get_name(), 'spectrum')
        E_time = time_spectrum['E'][0,0,0,:,:]
        t      = time_spectrum['t'][:,0]
        Ex = E_time[:,0]
        Ey = E_time[:,1]
        Ez = E_time[:,2]
        dt = t[1] - t[0]

        freqs_x, E_fft_x = compute_fft(Ex, dt, 100)
        freqs_y, E_fft_y = compute_fft(Ey, dt, 100)
        freqs_z, E_fft_z = compute_fft(Ez, dt, 100)

        E_fft_combined = np.sqrt(np.abs(E_fft_x)**2 + np.abs(E_fft_y)**2 + np.abs(E_fft_z)**2)
        E_power_spectrum = E_fft_combined**2
        E_power_spectrum = E_power_spectrum / np.max(E_power_spectrum)
        freqs = freqs_x
        with np.errstate(divide='ignore', invalid='ignore'):
            wvls = np.where(freqs != 0, c / freqs, np.inf)  # Avoid divide by zero

        peaks,_ = find_peaks(E_power_spectrum, height=0.02, distance=1) #
        all_res_wvls = wvls[peaks]
        res_wvls = np.array(all_res_wvls[np.abs(all_res_wvls - wavelength) < wavelength_span])
        closest_res_wvl = all_res_wvls[np.argmin(np.abs(all_res_wvls - wavelength))]

        plt.figure()
        plt.plot(wvls, E_power_spectrum)
        plt.scatter(all_res_wvls, E_power_spectrum[peaks], c='red')
        plt.title('Power Spectrum |E|^2')
        plt.xlabel('Wavelength (nm)')
        plt.ylabel('Power')
        plt.xlim((1500e-9, 1600e-9))
        plt.savefig(os.path.join(output_folder, 'FFT.png'))
        plt.close()
        

        if len(res_wvls) == 0:
            res_wvls = np.array([closest_res_wvl])

        if len(res_wvls) > 0:
            sim.switchtolayout()

            theta = 45
            x = np.cos(theta*np.pi/180)*(disk_radius - wavelength/16 - 5e-9)
            y = np.sin(theta*np.pi/180)*(disk_radius - wavelength/16 - 5e-9)
            Qanalysis = so.Qanalysis(x=x, y=y, z=wavelength/32+5e-9, 
                                    xspan = wavelength/8, yspan = wavelength/8, zspan = wavelength/16,
                                    nx=2, ny=2, nz = 2,
                                    fmin = c/(np.max(res_wvls) + wavelength_span/2), fmax = c/(np.min(res_wvls)-wavelength_span/2),
                                    start_time = 500e-15)

            Qanalysis.add_to_sim(sim)

            sim.run()
            try:
                sim.runanalysis()
                Qvals = sim.getresult(Qanalysis.get_name(), 'Q')
                Q = Qvals['Q']
                Q_res_wvls = Qvals['lambda']

                plt.figure(figsize=(8, 6))
                plt.plot(Q_res_wvls*1e9, Q, 'o')
                plt.xlabel('resonance wavelength (nm)')
                plt.ylabel('Q')
                plt.grid(True)
                plt.yscale('log')
                plt.savefig(os.path.join(output_folder, 'Q_vs_wvl.png'))
                plt.close()     
        
                Q_res_wvls = np.append(res_wvls, Q_res_wvls)
                Q_res_wvls = np.unique(Q_res_wvls)
            except Exception as e:
                print(f"Error: {e}")

            Q_res_wvls = res_wvls
            sim.switchtolayout()
            DFT_monitor_list = [None] * len(Q_res_wvls)
            for i in range(len(Q_res_wvls)):
                res = Q_res_wvls[i]
                DFT_monitor_list[i] = so.DFT_monitor(type='2D Z-normal',
                                            source_limits = 0,
                                            x=0, 
                                            y=0,
                                            z = 5e-9, 
                                            xspan = disk_radius*2 + 1.5e-6, 
                                            yspan = disk_radius*2 + 1.5e-6,
                                            num_freqs = 1, 
                                            wvl_center = res, 
                                            apodization = 'full',
                                            apodization_center = 3500e-15,
                                            apodization_width = 2000e-15)
                DFT_monitor_list[i].add_to_sim(sim)
            
            theta = 55
            x = np.cos(theta*np.pi/180)*(disk_radius - wavelength/8)
            y = np.sin(theta*np.pi/180)*(disk_radius - wavelength/8)
            DFT_monitor = so.DFT_monitor(x=x, y=y, z = 5e-9, num_freqs = 5000,
                                         wvl_center = np.mean(Q_res_wvls), wvl_span = 3*wavelength_span,
                                         source_limits = 0,
                                         apodization = 'full', apodization_center = 3500e-15, apodization_width = 2000e-15)
            DFT_monitor.add_to_sim(sim)

            sim.run()

            decay_lengths = np.zeros_like(Q_res_wvls)
            i = 0
            for field_profile in DFT_monitor_list:
                field_profile_data = sim.getresult(field_profile.get_name(), 'E')
                E_ = field_profile_data['E']
                E = E_[:,:,0,0,:]
                x = field_profile_data['x']
                y = field_profile_data['y']
                E_sq = np.abs((np.sum(E * np.conjugate(E), axis = 2)))

                x0 = np.argmin(np.abs(x))
                y0 = np.argmin(np.abs(y))

                x_pos = x[x0+20:-20]
                y_pos = y[y0+20:-20]

                sliced_E_sq = E_sq[x0+20:-20, y0+20:-20]
                
                max = 0
                for j in range(0, len(x_pos)):
                    for k in range(0, len(y_pos)):
                        if sliced_E_sq[j, k] > max:
                            max =  sliced_E_sq[j, k]
                            max_index_sliced = (j, k)
                sliced_E_sq = sliced_E_sq / max
                max_x = x_pos[max_index_sliced[1]]
                max_y = y_pos[max_index_sliced[0]]

                tangent_slope = -max_x / max_y
                perpendicular_slope = -1 / tangent_slope
                x1 = x_pos[0]
                y1 = max_y + perpendicular_slope *(x1 - max_x)
                x2 = x_pos[-1]
                y2 = max_y + (x2-max_x)*perpendicular_slope

                plt.figure(figsize=(8, 6))
                plt.imshow(sliced_E_sq, extent=[np.min(x_pos), np.max(x_pos), np.min(y_pos), np.max(y_pos)], origin='lower', cmap='viridis', aspect='auto')
                plt.plot([x1, x2], [y1, y2], 'r--')  # Plotting dashed line using indices
                plt.xlim(x_pos.min(), x_pos.max())
                plt.ylim(y_pos.min(), y_pos.max())
                plt.colorbar(label='Magnitude')  # Add a color bar to show the magnitude scale
                plt.xlabel('X axis')
                plt.ylabel('Y axis')
                plt.title('|E|^2')
                plt.savefig(os.path.join(output_folder, 'Esq_' + str(int(Q_res_wvls[i]*1e9)) + 'nm_.png'))
                plt.close()
                
                E_1d = []
                y_1d = []
                r_1d = []
                yvals = max_y + (x_pos - max_x)*perpendicular_slope
                for j in range(len(x_pos)):
                    yind = np.argmin(np.abs(y_pos - yvals[j]))
                    E_1d.append(sliced_E_sq[yind, j])
                    y_1d.append(y[yind])
                    r_1d.append(np.sqrt(x_pos[j]**2 + y_pos[yind]**2))
                
                threshold = 0.01
                for l, value in enumerate(E_1d):
                    if value > threshold:
                        index = l
                        break
                plt.figure(figsize=(8, 6))
                plt.plot(r_1d, E_1d, label='|E|^2 vs radial length')
                plt.axvline(x=disk_radius, color='r', linestyle='--')
                plt.xlabel('r (um)')
                plt.ylabel('|E|^2')
                plt.title(f"99pcnt field decay length: {(disk_radius - r_1d[index])*1e6} um")
                plt.xlim((0, disk_radius*3))
                plt.legend()
                plt.grid(True)
                plt.savefig(os.path.join(output_folder, 'E_1D_' + str(int(Q_res_wvls[i]*1e9)) + 'nm_.png'))
                plt.close()
                decay_lengths[i] = disk_radius - r_1d[index]

                i = i + 1

            spectrum = sim.getresult(DFT_monitor.get_name(), 'E')
            E = spectrum['E'][0,0,0,:,:]
            wvl = spectrum['lambda'][:,0]
            freqs = spectrum['f'][:,0]
            
            Esq = (np.sqrt(np.abs(np.sum(E * np.conjugate(E), axis = 1))))**2
            Esq = Esq / np.max(Esq)
            
            plt.figure(figsize=(8, 6))
            plt.plot(wvl*1e9, Esq, label='|E| vs wvl')
            plt.vlines(x=Q_res_wvls*1e9, ymin=np.zeros_like(Q_res_wvls), ymax=np.ones_like(Q_res_wvls), colors='r', linestyles='dashed')
            plt.xlabel('resonance wavelength (nm)')
            plt.ylabel('|E|^2')
            plt.grid(True)
            plt.savefig(os.path.join(output_folder, 'E_vs_wvl.png'))
            plt.close()

        results = {'resonance_wavelengths': res_wvls,
                    'Q_factors' : Q,
                    'Q_res_wvls': Q_res_wvls,
                    'decay_lengths': decay_lengths,
                    'Efield': Esq,
                    'wvl': wvl,
                    'Esq_time': E_power_spectrum,
                    'wvl_time': wvls}
        

        with open(os.path.join(output_folder, 'output.p'), 'wb') as f:
            pickle.dump(results, f)
        scipy.io.savemat(os.path.join(output_folder, 'output.mat'), results)
        return results

    except Exception as e:
        print(e)    
        return -1
        
def PhC_Q_Simulation(cavity = None,
                    sim_wvl = 955e-9, 
                    min_boundary_conditions = ["symmetric", "anti-symmetric", "PML"],
                    max_boundary_condition = "PML",
                    output_folder =  None, 
                    dimension = "3D",
                    mesh_accuracy = 2,
                    sim_time = 2e12,
                    use_fine_mesh = 1,
                    mesh_resolutions = [10e-9, 20e-9, 20e-9],
                    save_mode_profiles = 1,
                    cavity_name = 'cavity' + ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(10))):
    
    os.makedirs(output_folder, exist_ok=True)

    sim = lp.FDTD(hide=True)

    #Add FDTD Object
    fdtd = so.FDTD(x = 0, y = 0, z = 0,
                    xspan = (cavity.num_cav + cavity.num_mir + 10)*cavity.amir,
                    yspan = (math.ceil(cavity.wy/cavity.amir) + 8)*cavity.amir,
                    zspan = (math.ceil(cavity.wy/cavity.amir) + 8)*cavity.amir,
                    mesh_accuracy = 2,
                    dimension = dimension,
                    early_shutoff = 0,
                    max_BC = max_boundary_condition,
                    xmin_bc = min_boundary_conditions[0],
                    ymin_bc = min_boundary_conditions[1],
                    zmin_bc = min_boundary_conditions[2],
                    sim_time = sim_time)
    fdtd.add_to_sim(sim)

    #Add dipole sources
    dipole_1 = so.dipole(type = "Magnetic dipole",
                         x = 10e-9, y = 20e-9, z = 40e-9,
                         wvl_start = 0.95*sim_wvl,
                         wvl_stop = 1.05*sim_wvl)
    dipole_1.add_to_sim(sim)

    dipole_2 = so.dipole(type = "Magnetic dipole",
                         x = 20e-9, y = 30e-9, z = 10e-9,
                         wvl_start = 0.97*sim_wvl,
                         wvl_stop = 1.03*sim_wvl)
    dipole_2.add_to_sim(sim)

    #Q-analysis object
    Q_analysis = so.Qanalysis(t_start = 500e-12,
                              fmin = 3e8/(sim_wvl + 50e-9),
                              fmax = 3e8/(sim_wvl - 50e-9),
                              x = 20e-9, y = 20e-9, z = cavity.wz/6,
                              xspan = 10e-9, yspan = 10e-9, zspan = cavity.wz/3,
                              nx = 2, ny = 2, nz = 2)
    Q_analysis.add_to_sim(sim)

    if use_fine_mesh == 1:
        mesh = so.mesh(x = 0, y = 0, z = 0,
                       xspan = (cavity.num_cav + cavity.num_mir + 2*cavity.num_tap + 10)*cavity.amir,
                       yspan = 1.5*cavity.wy,
                       zspan = 1.5*cavity.wz,
                       x_resolution = mesh_resolutions[0],
                       y_resolution = mesh_resolutions[1],
                       z_resolution = mesh_resolutions[2])
        mesh.add_to_sim(sim)

    try:
        sim.run()
        sim.runanalysis()
        Qcal            = sim.getresult(Q_analysis.get_name(), "Q")
        maxQ            = np.max(Qcal['Q'])
        ind_maxQ        = np.argmax(Qcal['Q'])
        lambda_maxQ     = Qcal['lambda'][ind_maxQ]
        f_maxQ          = Qcal['f'][ind_maxQ]
    
        #Mode volume and mode-profile
        if save_mode_profiles == 1:
            sim.switchtolayout()
            ModeV_Monitor = so.Mode_Volume_Monitor(x = 0, y = 0, z = 0,
                                                xspan = (cavity.num_cav + cavity.num_mir + 2)*cavity.amir,
                                                yspan = (math.ceil(cavity.wy/cavity.amir) + 8)*cavity.amir - 3*cavity.amir,
                                                zspan = (math.ceil(cavity.wy/cavity.amir) + 8)*cavity.amir - 3*cavity.amir,
                                                analysis_wavelength = lambda_maxQ)
            ModeV_Monitor.add_to_sim(sim)

            xy_monitor = so.DFT_monitor(type='2D Z-normal',
                                        source_limits = 0,
                                        x=0, y=0, z = 0, 
                                        xspan = (cavity.num_cav + cavity.num_mir + 10)*cavity.amir, 
                                        yspan = (math.ceil(cavity.wy/cavity.amir) + 8)*cavity.amir,
                                        override = 1, num_freqs = 1, wvl_center = lambda_maxQ)
            xy_monitor.add_to_sim(sim)

            sim.run()
            sim.runanalysis()

            ModeV           = sim.getresult(ModeV_Monitor.get_name(), "Volume")
            ModeV_norm      = np.array(ModeV['V']) / ((lambda_maxQ / cavity.index)**3)
            ModeV           = ModeV['V']
            
            Exy     = sim.getresult(xy_monitor.get_name(), "E")
            Exy_x   = sim.getdata(xy_monitor.get_name(), "x")
            Exy_y   = sim.getdata(xy_monitor.get_name(), "y")
            Ey      = sim.getdata(xy_monitor.get_name(), "Ey")

            FieldProfile = {'Monitor_Data'  : Exy,
                            'x'             : Exy_x,
                            'y'             : Exy_y,
                            'Ey'            : Ey,
                            'Cavity'        : vars(cavity),
                            'Q'             : maxQ,
                            'wvl'           : lambda_maxQ,
                            'ModeVol'       : ModeV,
                            'ModeVolNorm'   : ModeV_norm}
            filename = f'FieldProfile_{str(cavity_name)}'
            scipy.io.savemat((filename + '.mat'), {'FieldProfile': FieldProfile})
            pickle.dump(FieldProfile, open((filename + '.p'), "wb"))
            
            return [maxQ, lambda_maxQ, ModeV, ModeV_norm]
        
        else:
            return [maxQ, lambda_maxQ]
        
    except Exception as e:
        print(f"No Resonance Found: {e}")
        return -1           
            
def microdisk_coupler(disk_radius, disk_thickness, material_index, coupler_width, coupler_gap, wavelength):
    sim = lp.FDTD(hide=True)

    output_folder = "coupler_width_" + str(int(coupler_width*1e9)) + "nm_gap_" + str(int(coupler_gap*1e9)) + "nm"
    os.makedirs(output_folder, exist_ok=True)

    sim.setglobalsource("wavelength start", wavelength)
    sim.setglobalsource("wavelength stop", wavelength)
    sim.setglobalmonitor("wavelength center", wavelength)
    sim.setglobalmonitor("wavelength span", 0)

    fdtd = so.FDTD(xspan = disk_radius + 2*wavelength, 
                   yspan = coupler_width*2 + 2*wavelength, 
                   zspan = disk_thickness + 2*wavelength, 
                   dimension = "3D", 
                   sim_time = 6e-12,
                   xmin_bc = 'PML',
                   ymin_bc = 'PML',
                   zmin_bc = 'PML',
                   mesh_accuracy = 3)
    fdtd.add_to_sim(sim)

    coupler = so.waveguide(x = 0,
                           y = 0,
                           z = 0,
                           wx = fdtd.xspan + 2*wavelength,
                           wy = coupler_width,
                           wz = disk_thickness,
                           index = material_index)
    coupler.add_to_sim(sim)

    disk = so.microdisk(thickness = disk_thickness, radius = disk_radius, index = material_index,
                        x = 0, z = 0, y = disk_radius + coupler_gap + coupler_width/2)
    disk.add_to_sim(sim)

    input_port = so.port(name = 'Input', x = -disk_radius/2 + wavelength, y = 0, z = 0, 
                          yspan = 1.5*wavelength, zspan = 1.5*wavelength)
    input_port.add_to_sim(sim)

    output_port = so.port(name = 'Output', x = disk_radius/2 - wavelength, y = 0, z = 0, 
                          yspan = 1.5*wavelength, zspan = 1.5*wavelength)
    output_port.add_to_sim(sim)

    ref_port = so.port(name = 'Reflection', x = -disk_radius/2 + wavelength/2, y = 0, z = 0, 
                          yspan = 1.5*wavelength, zspan = 1.5*wavelength,
                          direction = 'Backward')
    ref_port.add_to_sim(sim)

    field_monitor = so.DFT_monitor(type='2D Z-normal',
                                        source_limits = 0,
                                        x=0, 
                                        y=0,
                                        z = 0, 
                                        xspan = fdtd.xspan, 
                                        yspan = fdtd.yspan,
                                        num_freqs = 1, 
                                        wvl_center = wavelength, 
                                        apodization = 'none')
    field_monitor.add_to_sim(sim)

    if os.path.isfile('gui.fps'):
        os.remove('gui.fsp')
    sim.save('gui.fsp')
    
    try:
        sim.run()
        outport_result = sim.getresult(output_port.get_name(), 'expansion for port monitor')
        refport_result = sim.getresult(ref_port.get_name(), 'expansion for port monitor')
        Tnet = outport_result['T_total'] + refport_result['T_total']
        Tc = 1 - Tnet

        field_profile_data = sim.getresult(field_monitor.get_name(), 'E')
        E_ = field_profile_data['E']
        E = E_[:,:,0,0,:]
        x = field_profile_data['x']
        y = field_profile_data['y']
        E_sq = np.abs((np.sum(E * np.conjugate(E), axis = 2)))

        plt.figure(figsize=(8, 6))
        plt.imshow(np.transpose(E_sq), extent=[np.min(x), np.max(x), np.min(y), np.max(y)], 
                   origin='lower', cmap='viridis', aspect='auto') #, norm=LogNorm()
        #plt.xlim(x_pos.min(), x_pos.max())
        #plt.ylim(y_pos.min(), y_pos.max())
        plt.colorbar(label='Magnitude')  # Add a color bar to show the magnitude scale
        plt.xlabel('X axis')
        plt.ylabel('Y axis')
        plt.title('|E|^2')
        plt.savefig(os.path.join(output_folder, 'Esq.png'))
        plt.close()

        return Tc[0][0]
    
    except Exception as e:
        print(e)
        return -1

def rectangular_grating_sim(grating_width, grating_thickness, 
                            period, duty_cycle, 
                            num_gratings,
                            material_index, 
                            objective_NA, 
                            wavelength):
    sim = lp.FDTD(hide=True)

    #output_folder = "grating_width_" + str(int(grating_width*1e9)) + "nm_period_" + str(int(period*1e9)) + "nm_duty_cycle_" + str(int(duty_cycle*100))
    #os.makedirs(output_folder, exist_ok=True)

    grating_length = 2e-6

    sim.setglobalsource("wavelength start", 1550e-9)
    sim.setglobalsource("wavelength stop", 1550e-9)
    sim.setglobalmonitor("wavelength center", 1550e-9)
    sim.setglobalmonitor("wavelength span", 0)

    fdtd = so.FDTD(yspan = grating_width + 2*wavelength,
                   xspan = (num_gratings+1)*period + grating_length,
                   zspan = grating_thickness + 2*wavelength,
                   x = ((num_gratings+1)*period - grating_length)/2,
                   dimension = "3D",
                   sim_time = 2e-12,
                   xmin_bc = 'PML',
                   ymin_bc = 'anti-symmetric',
                   zmin_bc = 'PML',
                   mesh_accuracy = 3)
    fdtd.add_to_sim(sim)

    #Input waveguide
    input_waveguide = so.waveguide(x = -grating_length/2,
                                    y = 0,
                                    z = 0,
                                    wx = grating_length,
                                    wy = grating_width,
                                    wz = grating_thickness,
                                    index = material_index)   
    input_waveguide.add_to_sim(sim)

    #Grating
    grating = so.rectangular_grating(x_edge = 0, y = 0, z = 0,
                                     wy = grating_width, wz = grating_thickness,
                                     period = period, duty_cycle = duty_cycle,
                                     num_gratings = num_gratings,
                                     index = material_index)
    grating.add_to_sim(sim)

    #Input port
    input_port = so.port(name = 'Input', x = -1e-6, y = 0, z = 0,
                          yspan = 1.5*wavelength, zspan = 1.5*wavelength)
    input_port.add_to_sim(sim)

    #Thru port
    thru_port = so.port(name = 'Thru', x = num_gratings*period - wavelength, y = 0, z = 0,
                          yspan = 1.5*wavelength, zspan = 1.5*wavelength)
    thru_port.add_to_sim(sim)

    #Vertical port
    field_monitor = so.DFT_monitor(type='2D Z-normal',
                                        source_limits = 0,
                                        x=fdtd.x, 
                                        y=0,
                                        z = fdtd.zspan/2 - 200e-9, 
                                        xspan = fdtd.xspan, 
                                        yspan = fdtd.yspan,
                                        num_freqs = 1, 
                                        wvl_center = wavelength, 
                                        apodization = 'none')
    field_monitor.add_to_sim(sim)

    if os.path.isfile('gui.fps'):
        os.remove('gui.fsp')
    sim.save('gui.fsp')
    
    try:
        sim.run()
        outport_result = sim.getresult(field_monitor.get_name(), 'T')
        T = outport_result['T'][0]

        #refport_result = sim.getresult(ref_port.get_name(), 'expansion for port monitor')

        E = sim.farfield3d(field_monitor.get_name(),  1)
        ux = sim.farfieldux(field_monitor.get_name(),  1)
        uy = sim.farfielduy(field_monitor.get_name(),  1)

        halfangle=0.5*np.arcsin(objective_NA)*180/np.pi

        cone = sim.farfield3dintegrate(E, ux, uy, halfangle, 0, 0) 
        total = sim.farfield3dintegrate(E, ux, uy) 
        ratio = cone/total  

        field_profile_data = sim.getresult(field_monitor.get_name(), 'E')
        E_ = field_profile_data['E']
        E = E_[:,:,0,0,:]
        x = field_profile_data['x']
        y = field_profile_data['y']
        E_sq = np.abs((np.sum(E * np.conjugate(E), axis = 2)))

        #plt.figure(figsize=(8, 6))
        #plt.imshow(np.transpose(E_sq), extent=[np.min(x), np.max(x), np.min(y), np.max(y)], 
        #           origin='lower', cmap='viridis', aspect='auto') #, norm=LogNorm()
        #plt.xlim(x_pos.min(), x_pos.max())
        #plt.ylim(y_pos.min(), y_pos.max())
        #plt.colorbar(label='Magnitude')  # Add a color bar to show the magnitude scale
        #plt.xlabel('X axis')
        #plt.ylabel('Y axis')
        #plt.title('|E|^2')
        #plt.savefig(os.path.join(output_folder, 'Esq.png'))
        #plt.close()

        T_total = T*ratio
        print(T, ratio, T_total)
        return [T, ratio, T_total]
    
    except Exception as e:
        print(e)
        return -1