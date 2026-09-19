#include <Wire.h>

// The sensor is wired to A4 (SDA) / A5 (SCL). On the Arduino UNO Q those pins are the
// Wire2 I2C bus; plain Wire is the separate SDA/SCL pair next to AREF.
#define IMU_WIRE  Wire2

// MPU6050 / MPU9150 / MPU9250 registers
// AD0 low = 0x68 (default), AD0 high = 0x69
#define MPU_ADDRESS           0x68
#define MPU_RA_GYRO_CONFIG    0x1B
#define MPU_RA_ACCEL_CONFIG   0x1C
#define MPU_RA_INT_PIN_CFG    0x37
#define MPU_RA_ACCEL_XOUT_H   0x3B
#define MPU_RA_USER_CTRL      0x6A
#define MPU_RA_PWR_MGMT_1     0x6B
#define MPU_RA_WHO_AM_I       0x75
#define MPU_PWR1_SLEEP        0x40 // PWR_MGMT_1 sleep bit, set when the chip powers up

// The magnetometer (AK8975 in the MPU9150, AK8963 in the MPU9250) sits behind the MPU
// at its own I2C address. The MPU6050 has no magnetometer.
#define MAG_ADDRESS           0x0C
#define MAG_RA_WIA            0x00
#define MAG_RA_XOUT_L         0x03
#define MAG_RA_CNTL           0x0A

uint8_t buffer_m[6];

int16_t ax, ay, az;
int16_t gx, gy, gz;
int16_t mx, my, mz;

float heading;
float tiltheading;

float Axyz[3];
float Gxyz[3];
float Mxyz[3];

bool compassFound = false;
bool sensorOk = false;
unsigned long readingCount = 0;
unsigned long sensorResets = 0;

#define sample_num_mdate  5000

volatile float mx_sample[3];
volatile float my_sample[3];
volatile float mz_sample[3];

static float mx_centre = 0;
static float my_centre = 0;
static float mz_centre = 0;

volatile int mx_max = 0;
volatile int my_max = 0;
volatile int mz_max = 0;

volatile int mx_min = 0;
volatile int my_min = 0;
volatile int mz_min = 0;

bool writeReg(uint8_t addr, uint8_t reg, uint8_t value)
{
    IMU_WIRE.beginTransmission(addr);
    IMU_WIRE.write(reg);
    IMU_WIRE.write(value);
    return IMU_WIRE.endTransmission() == 0;
}

bool readRegs(uint8_t addr, uint8_t reg, uint8_t length, uint8_t *data)
{
    IMU_WIRE.beginTransmission(addr);
    IMU_WIRE.write(reg);
    if (IMU_WIRE.endTransmission() != 0) return false;
    if (IMU_WIRE.requestFrom(addr, (size_t)length) != length) return false;
    for (uint8_t i = 0; i < length; i++) data[i] = IMU_WIRE.read();
    return true;
}

int readReg(uint8_t addr, uint8_t reg)
{
    uint8_t value;
    return readRegs(addr, reg, 1, &value) ? value : -1;
}

void initIMU()
{
    writeReg(MPU_ADDRESS, MPU_RA_PWR_MGMT_1, 0x01);   // wake up, clock from the X gyro PLL
    writeReg(MPU_ADDRESS, MPU_RA_GYRO_CONFIG, 0x00);  // +/- 250 degrees/s
    writeReg(MPU_ADDRESS, MPU_RA_ACCEL_CONFIG, 0x00); // +/- 2g
    writeReg(MPU_ADDRESS, MPU_RA_USER_CTRL, 0x00);    // I2C master mode off
    writeReg(MPU_ADDRESS, MPU_RA_INT_PIN_CFG, 0x02);  // I2C bypass on: exposes the magnetometer
    delay(10);
}

// The MPU6050/MPU9150 powers up asleep and then reads all zeros. If it is ever found asleep
// it has reset (usually a brief power loss from a loose VCC/GND wire), so wake it up again.
void checkSensorAwake()
{
    int pwr = readReg(MPU_ADDRESS, MPU_RA_PWR_MGMT_1);
    if (pwr >= 0 && (pwr & MPU_PWR1_SLEEP)) {
        initIMU();
        sensorResets++;
    }
}

// WHO_AM_I: 0x68 = MPU6050/MPU9150, 0x70 = MPU6500, 0x71 = MPU9250, 0x73 = MPU9255
bool mpuConnected()
{
    int id = readReg(MPU_ADDRESS, MPU_RA_WHO_AM_I);
    return id == 0x68 || id == 0x70 || id == 0x71 || id == 0x73;
}

void setup() {
  // join I2C bus
  IMU_WIRE.begin();

  // initialize serial communication
  // (38400 chosen because it works as well at 8MHz as it does at 16MHz, but
  // it's really up to you depending on your project)
  Serial.begin(38400);

  // initialize device
  Serial.println("Initializing I2C devices...");
  initIMU();

  // verify connection
    Serial.println("Testing device connections...");
    Serial.println(mpuConnected() ? "MPU connection successful" : "MPU connection failed");
    compassFound = readReg(MAG_ADDRESS, MAG_RA_WIA) == 0x48;
    Serial.println(compassFound ? "Compass connection successful" : "Compass not found");
    delay(1000);
    Serial.println("     ");

 //Mxyz_init_calibrated ();
}

void loop()
{
    checkSensorAwake();
    getAccel_Data();
    getGyro_Data();
    getCompassDate_calibrated(); // compass data has been calibrated here
    getHeading();               //before we use this function we should run 'getCompassDate_calibrated()' frist, so that we can get calibrated data ,then we can get correct angle .
    getTiltHeading();

    // On the UNO Q every Serial.print() is sent to the Linux side as a separate message,
    // so build the whole reading first and send it with a single print.
    String out;
    out.reserve(800);

    out += "Reading #";
    out += ++readingCount;
    out += "\n";
    if (!sensorOk) {
        out += "Sensor read failed (I2C), so the values below are old.\n";
    }
    if (sensorResets > 0) {
        out += "Sensor has reset ";
        out += sensorResets;
        out += " time(s) and was woken up again - check the VCC/GND wires.\n";
    }
    if (!compassFound) {
        out += "No compass found (an MPU6050 has none), so compass and heading values stay 0.\n";
    }
    out += "\n";

    out += "calibration parameter: \n";
    out += String(mx_centre) + "         " + String(my_centre) + "         " + String(mz_centre) + "\n";
    out += "\n";

    out += "Acceleration(g) of X,Y,Z:\n";
    out += String(Axyz[0]) + "," + String(Axyz[1]) + "," + String(Axyz[2]) + "\n";
    out += "Gyro(degress/s) of X,Y,Z:\n";
    out += String(Gxyz[0]) + "," + String(Gxyz[1]) + "," + String(Gxyz[2]) + "\n";
    out += "Compass Value of X,Y,Z:\n";
    out += String(Mxyz[0]) + "," + String(Mxyz[1]) + "," + String(Mxyz[2]) + "\n";
    out += "The clockwise angle between the magnetic north and X-Axis:\n";
    out += String(heading) + "\n";
    out += "The clockwise angle between the magnetic north and the projection of the positive X-Axis in the horizontal plane:\n";
    out += String(tiltheading) + "\n";
    out += "\n\n\n";

    Serial.print(out);
    delay(300);
}


void getHeading(void)
{
    heading = 180 * atan2(Mxyz[1], Mxyz[0]) / PI;
    if (heading < 0) heading += 360;
}

void getTiltHeading(void)
{
    float pitch = asin(-Axyz[0]);
    float roll = asin(Axyz[1] / cos(pitch));

    float xh = Mxyz[0] * cos(pitch) + Mxyz[2] * sin(pitch);
    float yh = Mxyz[0] * sin(roll) * sin(pitch) + Mxyz[1] * cos(roll) - Mxyz[2] * sin(roll) * cos(pitch);
    float zh = -Mxyz[0] * cos(roll) * sin(pitch) + Mxyz[1] * sin(roll) + Mxyz[2] * cos(roll) * cos(pitch);
    tiltheading = 180 * atan2(yh, xh) / PI;
    if (yh < 0)    tiltheading += 360;
}

void Mxyz_init_calibrated ()
{
    Serial.println(F("Before using 9DOF,we need to calibrate the compass frist,It will takes about 2 minutes."));
    Serial.print("  ");
    Serial.println(F("During  calibratting ,you should rotate and turn the 9DOF all the time within 2 minutes."));
    Serial.print("  ");
    Serial.println(F("If you are ready ,please sent a command data 'ready' to start sample and calibrate."));
    while (!Serial.find("ready"));
    Serial.println("  ");
    Serial.println("ready");
    Serial.println("Sample starting......");
    Serial.println("waiting ......");

    get_calibration_Data ();

    Serial.println("     ");
    Serial.println("compass calibration parameter ");
    Serial.print(mx_centre);
    Serial.print("     ");
    Serial.print(my_centre);
    Serial.print("     ");
    Serial.println(mz_centre);
    Serial.println("    ");
}

void get_calibration_Data ()
{
    for (int i = 0; i < sample_num_mdate; i++)
    {
        get_one_sample_date_mxyz();
        /*
        Serial.print(mx_sample[2]);
        Serial.print(" ");
        Serial.print(my_sample[2]);                            //you can see the sample data here .
        Serial.print(" ");
        Serial.println(mz_sample[2]);
        */

        if (mx_sample[2] >= mx_sample[1])mx_sample[1] = mx_sample[2];
        if (my_sample[2] >= my_sample[1])my_sample[1] = my_sample[2]; //find max value
        if (mz_sample[2] >= mz_sample[1])mz_sample[1] = mz_sample[2];

        if (mx_sample[2] <= mx_sample[0])mx_sample[0] = mx_sample[2];
        if (my_sample[2] <= my_sample[0])my_sample[0] = my_sample[2]; //find min value
        if (mz_sample[2] <= mz_sample[0])mz_sample[0] = mz_sample[2];
    }

    mx_max = mx_sample[1];
    my_max = my_sample[1];
    mz_max = mz_sample[1];

    mx_min = mx_sample[0];
    my_min = my_sample[0];
    mz_min = mz_sample[0];

    mx_centre = (mx_max + mx_min) / 2;
    my_centre = (my_max + my_min) / 2;
    mz_centre = (mz_max + mz_min) / 2;
}

void get_one_sample_date_mxyz()
{
    getCompass_Data();
    mx_sample[2] = Mxyz[0];
    my_sample[2] = Mxyz[1];
    mz_sample[2] = Mxyz[2];
}

// reads accel (0x3B-0x40), temperature (0x41-0x42) and gyro (0x43-0x48) in one go
void getMotion6(void)
{
    uint8_t raw[14];
    sensorOk = readRegs(MPU_ADDRESS, MPU_RA_ACCEL_XOUT_H, 14, raw);
    if (!sensorOk) return;

    ax = ((int16_t)raw[0] << 8) | raw[1];
    ay = ((int16_t)raw[2] << 8) | raw[3];
    az = ((int16_t)raw[4] << 8) | raw[5];
    gx = ((int16_t)raw[8] << 8) | raw[9];
    gy = ((int16_t)raw[10] << 8) | raw[11];
    gz = ((int16_t)raw[12] << 8) | raw[13];
}

void getAccel_Data(void)
{
    getMotion6();
    Axyz[0] = (double) ax / 16384;
    Axyz[1] = (double) ay / 16384;
    Axyz[2] = (double) az / 16384;
}

void getGyro_Data(void)
{
    getMotion6();
    Gxyz[0] = (double) gx * 250 / 32768;
    Gxyz[1] = (double) gy * 250 / 32768;
    Gxyz[2] = (double) gz * 250 / 32768;
}

void getCompass_Data(void)
{
    if (!compassFound) return;

    writeReg(MAG_ADDRESS, MAG_RA_CNTL, 0x01); //enable the magnetometer (single measurement)
    delay(10);
    if (!readRegs(MAG_ADDRESS, MAG_RA_XOUT_L, 6, buffer_m)) return;

    mx = ((int16_t)(buffer_m[1]) << 8) | buffer_m[0] ;
    my = ((int16_t)(buffer_m[3]) << 8) | buffer_m[2] ;
    mz = ((int16_t)(buffer_m[5]) << 8) | buffer_m[4] ;

    Mxyz[0] = (double) mx * 1200 / 4096;
    Mxyz[1] = (double) my * 1200 / 4096;
    Mxyz[2] = (double) mz * 1200 / 4096;
}

void getCompassDate_calibrated ()
{
    getCompass_Data();
    Mxyz[0] = Mxyz[0] - mx_centre;
    Mxyz[1] = Mxyz[1] - my_centre;
    Mxyz[2] = Mxyz[2] - mz_centre;
}
