import serial


class Dmm:
    """
    Takes readings off the serial port from a class of multimeters that includes
    the TekPower TP4000ZC (the meter I own) and supposedly is the same as the the
    'VC820' mode in QtDMM.

    example code:

    # load the module
    import tp4000zc

    # the port that we're going to use.  This can be a number or device name.
    # on linux or posix systems this will look like /dev/tty2 or /dev/ttyUSB0
    # on windows this will look something like COM3
    port = '/dev/ttyUSB0'

    # get an instance of the class
    dmm = tp4000zc.Dmm(port)

    # read a value
    val = dmm.read()

    print val.text       # print the text representation of the value
                         # something like: -4.9 millivolts DC
    print val.numericVal # and the numeric value
                         # ie: -0.0048
    # recycle the serial port
    dmm.close()


    Public Interface:
    __init__(port, retries=3, timeout=3.0):
        Instantiating the class attempts to open the serial port specified,
        initialize it and read enough from the serial port to synchronize
        the module with the start/end of a full reading.

    read():
        Attempt to get a complete reading off of the serial port, parse it and
        return an instance of DmmValue holding the interpretted reading.

    close():
        Finally you can close the serial port connection with close()

    Exceptions will be raised if
       * PySerial raises an exception (SerialException or ValueError)
       * this module can't get a full reading that passes initial data integrity
         checks (subclasses of DmmException)
       * I made a coding error (whatever python might throw)

    If no exceptions are raised the DmmValue might still fail various sanity
    checks or not have a numeric value.  Ie I believe that showing showing
    multiple decimal points makes no sense but is valid per the protocol so
    no exception is raised but the saneValue flag will be set to False in the
    DmmValue.

    Meter Documentation:

    Per the documentation page, the meter spits out readings which are bursts of
    14 bytes every .25 seconds.  The high nibble of each byte is the byte number
    (1-14) for synchronization and sanity checks, the low nibble holds the data.

    Each data bit represents an individual field on the LCD display of the meter,
    from segments of the 7 segment digits to individual flags.  Bytes 1 and 10-14
    are flags (with four bits reserved/unmapped on this meter) and bytes (2,3),
    (4,5), (6,7) and (8,9) representing the individual digits on the display.

    For the digits, if the high bit of the first nibble of a digit is set then the
    negative sign (for the first digit) or the leading decimal point is turned on.
    the remaining bits of the two nibbles represent the elements of the 7 segment
    digit display as follows:

      pos 3       nibble 1:   S123
     p     p      nibble 2:   4567
     o     o      where S is either the sign or decimal bit.
     s     s
     2     7      The legal values of the segment bits are represented in
      pos 6       digitTable and include the digits 0-9 along with blank and
     p     p      'L'.
     o     o
     s     s
     1     5
      pos 4

    Serial settings for this meter are:
    2400 baud 8N1
    """

    bytesPerRead = 14

    def __init__(self, port='/dev/ttyUSB0', retries = 3, timeout = 3.0):
        self.ser = serial.Serial(
            port = port,
            baudrate = 2400,
            parity = serial.PARITY_NONE,
            stopbits = serial.STOPBITS_ONE,
            bytesize = serial.EIGHTBITS,
            timeout = timeout)
        self.retries = retries # the number of times it's allowed to retry to get a valid 14 byte read

        self._synchronize()

    def close(self):
        "Close the serial port connection."
        self.ser.close()

    def read(self):
        "Attempt to take a reading from the digital multimeter."

        # first get a set of bytes and validate it.
        # if the first doesn't validate, synch and get a new set.
        for readAttempt in range(self.retries):
            data = self.ser.read(self.bytesPerRead)
            if len(data) == self.bytesPerRead:
                for pos, byte in enumerate(data, start=1):
                    if byte // 16 != pos:
                        break
                else:
                    break

            if (readAttempt + 1) >= self.retries:
                raise DmmReadFailure()

            self._synchronize()

        val = ''
        for (d1,d2,ch) in self.digits:
            highBit, digit = self._readDigit(data[d1-1], data[d2-1])
            if highBit:
                val = val + ch
            val = val + digit

        attribs = {
            'flags': [],
            'scale': [],
            'measure': [],
            'other': [],
        }

        for k,v in self.bits.items():
            self._readAttribByte(data[k-1], v, attribs)

        return DmmValue(val, attribs, readAttempt, data)


    def _synchronize(self):
        v = self.ser.read(1)
        if not v:
            raise DmmNoData()
        pos = v[0] // 16
        if pos in (0, 15):
            raise DmmInvalidSyncValue()

        bytesNeeded = self.bytesPerRead - pos
        if bytesNeeded:
            v = self.ser.read(bytesNeeded)
            # should we check the validity of these bytes?
            # the read() function allows an occasional invalid
            # read without throwing an exception so for now
            # I'll say no.


    bits = {
        1: [('flags', 'AC'), ('flags', 'DC'), ('flags', 'AUTO'), ('flags', 'RS232')],
        10:[('scale', 'micro'), ('scale', 'nano'), ('scale', 'kilo'), ('measure', 'diode')],
        11:[('scale', 'milli'), ('measure', '% (duty-cycle)'), ('scale', 'mega'),
            ('flags', 'beep')],
        12:[('measure', 'Farads'), ('measure', 'Ohms'), ('flags', 'REL delta'),
            ('flags', 'Hold')],
        13:[('measure', 'Amps'), ('measure', 'volts'), ('measure', 'Hertz'),
            ('other', 'other_13_1')],
        14:[('other', 'other_14_4'), ('measure', 'degrees Celcius'), ('other', 'other_14_2'),
            ('other', 'other_14_1')]}

    digits = [(2,3,'-'), (4,5,'.'), (6,7,'.'), (8,9,'.')]
    digitTable = {(0,5):'1', (5,11):'2', (1,15):'3', (2,7):'4', (3,14):'5',
                  (7,14):'6', (1,5):'7', (7,15):'8', (3,15):'9', (7,13):'0',
                  (6,8):'L', (0,0):' '}

    def _readAttribByte(self, byte, bits, attribs):
        b = byte % 16
        bitVal = 8
        for (attr, val) in bits:
            if b // bitVal:
                b -= bitVal
                #print "adding flag type %s, val %s"%(attr, val)
                attribs[attr].append(val)
            bitVal //= 2

    def _readDigit(self, byte1, byte2):
        b1 = byte1 % 16
        highBit = b1 // 8
        b1 = b1 % 8
        b2 = byte2 % 16
        try:
            digit = self.digitTable[(b1,b2)]
        except:
            digit = 'X'
        return highBit, digit


class DmmValue:
    """
    This is a representation of a single read from the multimeter.

    Attributes in rough order of usefulness:

    Sanity checks:
       saneValue: True if no sanity checks failed.

    High level computed fields:
       text: Nicely formatted text representation of the value.
       numericVal: numeric value after SI prefixes applied or None if value is non-numeric.
       measurement: what is being measured.
       delta: True if the meter is in delta mode.
       ACDC: 'AC', 'DC' or None.
       readErrors:  Number of failed reads attempts before successfully getting a reading
           from the meter.

    Other, possibly useful, computed fields:
       val: cleaned up display value
       scale: SI prefix for val

    Unprocessed values:
       rawVal: Numeric display
       flags: Various flags modifying the measurement
       scaleFlags: SI scaling factor flags
       measurementFlags: Flags to specify what the meter is measuring
       reservedFlags: Flags that are undefined
       rawBytes:  the raw, 14 byte bitstream that produced this value.

    """
    def __init__(self, val, attribs, readErrors, rawBytes):
        self.saneValue = True
        self.rawVal = self.val = val
        self.flags = attribs['flags']
        self.scaleFlags = attribs['scale']
        self.measurementFlags = attribs['measure']
        self.reservedFlags = attribs['other']
        self.readErrors = readErrors
        self.rawBytes = rawBytes
        self.text = 'Invalid Value'

        self.processFlags()
        self.processScale()
        self.processMeasurement()
        self.processVal()

        if self.saneValue:
            self.createTextExpression()

    def createTextExpression(self):
        self.text = (
            f"{self.deltaText}{self.val} {self.scale}{self.measurement}{self.ACDCText}"
        )

    def processFlags(self):
        flags = self.flags
        self.ACDC = None
        self.ACDCText = ''
        self.delta = False
        self.deltaText = ''

        if 'AC' in flags and 'DC' in flags:
            self.saneValue = False
        if 'AC' in flags:
            self.ACDC = 'AC'
        if 'DC' in flags:
            self.ACDC = 'DC'
        if self.ACDC is not None:
            self.ACDCText = ' ' + self.ACDC
        if 'REL delta' in flags:
            self.delta = True
            self.deltaText = 'delta '

    scaleTable = {'nano': 0.000000001, 'micro': 0.000001, 'milli': 0.001,
                  'kilo': 1000.0, 'mega': 1000000.0}
    def processScale(self):
        s = self.scaleFlags
        self.scale = ''
        self.multiplier = 1

        if s:
            if len(s) > 1:
                self.saneValue = False
            else:
                self.scale = s[0]
                self.multiplier = self.scaleTable[self.scale]

    def processMeasurement(self):
        m = self.measurementFlags
        if len(m) == 1:
            self.measurement = m[0]
        else:
            self.measurement = None
            self.saneValue = False

    def processVal(self):
        v = self.rawVal
        self.numericVal = None
        if 'X' in v or v.count('.') > 1:
            self.saneValue = False
        else:
            try:
                n = float(v)
            except ValueError:
                return

            self.val = str(n)
            self.numericVal = n * self.multiplier

    def __repr__(self):
        return "<DmmValue instance: %s>"%self.text


class DmmException(Exception):
    "Base exception class for Dmm."

class DmmNoData(DmmException):
    "Read from serial port timed out with no bytes read."

class DmmInvalidSyncValue(DmmException):
    "Got an invalid byte during syncronization."

class DmmReadFailure(DmmException):
    "Unable to get a successful read within the number of allowed retries."


def main():
    dmm = Dmm()

    while True:
        val = dmm.read()
        print(val.text)
        print(val.numericVal)

# main hook
if __name__ == "__main__":
    main()
