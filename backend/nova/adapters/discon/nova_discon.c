/*
 * Nova DISCON: Bladed-style controller library for OpenFAST ServoDyn (PCMode = VSContrl = 5).
 *
 * It reproduces Nova's control blocks so that the native aeroelastic simulation and OpenFAST run the same
 * controller:
 *   generator torque (low-speed shaft)  T = k * w^2, capped at rated_torque; sent as T / gearbox_ratio;
 *   collective pitch (deg)              u = offset + g * (kp * e + ki * integral(e)), e = w - setpoint
 *                                       (reverse = 1) or setpoint - w, limited to [pitch_min, pitch_max]
 *                                       with conditional integration (anti-windup);
 *   gain schedule g(pitch)              linear table of up to 16 points (optional), g = 1 otherwise.
 * w is the rotor (low-speed shaft) speed, avrSWAP record 21. The parameter file (DLL_InFile) holds
 * "name value" lines; unknown names are an error.
 *
 * Interface: void DISCON(float *avrSWAP, int *aviFAIL, const char *accINFILE, const char *avcOUTNAME, char *avcMSG)
 * (records as in OpenFAST modules/servodyn/src/BladedInterface.f90).
 *
 * SPDX-License-Identifier: Apache-2.0
 */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MAX_SCHEDULE 16
#define DEG (3.14159265358979323846 / 180.0)

static double k_torque, rated_torque = 1e30, gearbox = 1.0;
static double kp, ki, setpoint, pitch_min = 0.0, pitch_max = 90.0, offset = 0.0, reverse = 1.0, pitch_enabled = 1.0;
static int schedule_n = 0;
static double schedule_x[MAX_SCHEDULE], schedule_y[MAX_SCHEDULE];
static double integral = 0.0, last_time = -1.0, last_pitch = 0.0;

static void message(char *avcMSG, int size, const char *text) {
    if (size > 0) {
        strncpy(avcMSG, text, (size_t)size - 1);
        avcMSG[size - 1] = '\0';
    }
}

static int read_parameters(const char *path, char *error, int size) {
    FILE *file = fopen(path, "r");
    char line[512], name[128];
    double value;
    if (!file) {
        snprintf(error, (size_t)size, "Nova DISCON: cannot open %s", path);
        return -1;
    }
    while (fgets(line, sizeof line, file)) {
        if (line[0] == '#' || line[0] == '\n') continue;
        if (sscanf(line, "%127s %lf", name, &value) != 2) continue;
        if (!strcmp(name, "torque_k")) k_torque = value;
        else if (!strcmp(name, "rated_torque")) rated_torque = value;
        else if (!strcmp(name, "gearbox_ratio")) gearbox = value;
        else if (!strcmp(name, "kp")) kp = value;
        else if (!strcmp(name, "ki")) ki = value;
        else if (!strcmp(name, "setpoint")) setpoint = value;
        else if (!strcmp(name, "pitch_min")) pitch_min = value;
        else if (!strcmp(name, "pitch_max")) pitch_max = value;
        else if (!strcmp(name, "offset")) offset = value;
        else if (!strcmp(name, "reverse")) reverse = value;
        else if (!strcmp(name, "pitch_enabled")) pitch_enabled = value;
        else if (!strcmp(name, "schedule_point")) {
            double gain;
            if (schedule_n >= MAX_SCHEDULE || sscanf(line, "%*s %lf %lf", &value, &gain) != 2) {
                fclose(file);
                snprintf(error, (size_t)size, "Nova DISCON: bad schedule_point line");
                return -1;
            }
            schedule_x[schedule_n] = value;
            schedule_y[schedule_n] = gain;
            schedule_n++;
        } else {
            fclose(file);
            snprintf(error, (size_t)size, "Nova DISCON: unknown parameter %s", name);
            return -1;
        }
    }
    fclose(file);
    if (gearbox <= 0.0) {
        snprintf(error, (size_t)size, "Nova DISCON: gearbox_ratio must be positive");
        return -1;
    }
    return 0;
}

static double schedule(double pitch_deg) {
    int i;
    if (schedule_n == 0) return 1.0;
    if (pitch_deg <= schedule_x[0]) return schedule_y[0];
    for (i = 1; i < schedule_n; i++)
        if (pitch_deg <= schedule_x[i])
            return schedule_y[i - 1] + (schedule_y[i] - schedule_y[i - 1]) * (pitch_deg - schedule_x[i - 1]) / (schedule_x[i] - schedule_x[i - 1]);
    return schedule_y[schedule_n - 1];
}

void DISCON(float *avrSWAP, int *aviFAIL, const char *accINFILE, const char *avcOUTNAME, char *avcMSG) {
    int status = (int)lround(avrSWAP[0]);
    int message_size = (int)lround(avrSWAP[48]);
    double time = avrSWAP[1], speed = avrSWAP[20], torque, pitch, error_value, trial, command, dt;
    (void)avcOUTNAME;
    *aviFAIL = 0;
    if (status == 0) {
        char error[256] = "";
        integral = 0.0;
        last_time = time;
        last_pitch = avrSWAP[3] / DEG;
        schedule_n = 0;
        if (read_parameters(accINFILE, error, sizeof error) != 0) {
            message(avcMSG, message_size, error);
            *aviFAIL = -1;
            return;
        }
    }
    if (status < 0) return;
    dt = last_time >= 0.0 ? time - last_time : 0.0;
    if (dt < 0.0) dt = 0.0;
    last_time = time;
    /* generator torque */
    torque = k_torque * speed * fabs(speed);
    if (torque > rated_torque) torque = rated_torque;
    /* collective pitch */
    pitch = last_pitch;
    if (pitch_enabled > 0.5) {
        error_value = reverse > 0.5 ? speed - setpoint : setpoint - speed;
        trial = integral + ki * error_value * dt;
        command = offset + schedule(last_pitch) * (kp * error_value + trial);
        pitch = command < pitch_min ? pitch_min : command > pitch_max ? pitch_max : command;
        if (pitch == command || (command > pitch && error_value < 0) || (command < pitch && error_value > 0)) integral = trial;
        last_pitch = pitch;
    }
    avrSWAP[34] = 1.0f;                      /* record 35: generator contactor on */
    avrSWAP[35] = 0.0f;                      /* record 36: shaft brake off */
    avrSWAP[40] = 0.0f;                      /* record 41: yaw actuator torque */
    avrSWAP[41] = (float)(pitch * DEG);      /* records 42-44: individual pitch (same value) */
    avrSWAP[42] = (float)(pitch * DEG);
    avrSWAP[43] = (float)(pitch * DEG);
    avrSWAP[44] = (float)(pitch * DEG);      /* record 45: collective pitch (rad) */
    avrSWAP[46] = (float)(torque / gearbox); /* record 47: generator torque (HSS, N m) */
    avrSWAP[47] = 0.0f;                      /* record 48: yaw rate */
    avrSWAP[54] = 0.0f;                      /* record 55: no pitch override */
    avrSWAP[55] = 0.0f;                      /* record 56: no torque override */
    avrSWAP[64] = 0.0f;                      /* record 65: no logging channels */
}
