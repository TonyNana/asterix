"""asterix/applet.py

__author__ = "Petr Tobiska"

Author: Petr Tobiska, mailto:petr.tobiska@gmail.com, petr.tobiska@gemalto.com
Date: 2015-11-16

This file is part of asterix, a framework for communication with smartcards
based on pyscard. This file implementes JavaCard Applet load/install/delete
APDU.

asterix is free software; you can redistribute it and/or modify
it under the terms of the GNU Lesser General Public License as published by
the Free Software Foundation; either version 2.1 of the License, or
(at your option) any later version.

asterix is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU Lesser General Public License for more details.

You should have received a copy of the GNU Lesser General Public License
along with pyscard; if not, write to the Free Software
Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA  02110-1301  USA

"""

from binascii import hexlify, unhexlify
from struct import pack
import hashlib
# PyCrypto
from Crypto.Hash import SHA
from Crypto.Signature import PKCS1_v1_5
from Crypto.PublicKey import RSA
from Crypto.Util import number
# asterix
from formutil import int2s, derLen
__all__ = ( 'Applet', 'RSAtoken', 'DEStoken' )

def berlv( strval ):
    """ Prepend length (coded as ASN1 DER) of the strval and return as LV."""
    return derLen( strval ) + strval

INS_DELETE  = 0xE4
INS_INSTALL = 0xE6
INS_LOAD    = 0xE8
P1_INST_LOAD    = 0x02
P1_INST_INST    = 0x04
P1_INST_MSEL    = 0x08
P1_INST_INSMSEL = P1_INST_INST | P1_INST_MSEL
P1_INST_EXTRA   = 0x10
P1_INST_PERSO   = 0x20
P1_INST_REGUPD  = 0x40

class Applet:
    """ Class for generating load/install/delete APDU. """

    def __init__( self, **kw ):
        """ Constructor of Applet object.
Expected parameters (in dict):
  AID_package  - (string, mandatory)
  AID_module   - (string, mandatory)
  AID_instance - (string, optional, default AID_module)
  AID_SD       - (string, optional, default not present)
  privileges   - (string, optional, default '\0'
  par_sys      - System specific params, tag EF, list of strings
                 optional, default ['C8020000', 'C7020000'] + SIMtoolkit
  par_sys_sim  - SIM file access and Toolkit app. specific params, tag EF/CA,
                 optional, default not present
  par_UICC_toolkit - UICC toolkit app. specific, tag EA/80, string,
                 optional, default: not present
  par_UICC_DAP
  par_UICC_access
  par_UICC_admin_access
  par_applet   - applet specific parameters, tag C9, string, optional
  file_ijc     - path/filename to *.ijc
"""
        keywords = ( 'AID_package', 'AID_module', 'AID_instance',
                     'privileges',
                     'par_sys', 'par_sys_sim',
                     'par_UICC_toolkit', 'par_UICC_DAP',
                     'par_UICC_access', 'par_UICC_admin_access',
                     'par_applet',
                     'file_ijc' )
        for k in keywords:
            if k in kw: self.__dict__[k] = kw[k]

    def install_inst( self, token = None ):
        """ Build Install for install APDU.
  token        - instance of Token, calculates token for Delegated
                 management if present"""
        privileges = 'privileges' in self.__dict__ \
                     and self.privileges or '\x00'
        if 'par_sys' in self.__dict__:
            sys_spec_par = ''.join( self.par_sys )
        else:
            sys_spec_par = unhexlify( "C7020000C8020000" )
        if 'par_sys_sim' in self.__dict__:
            sys_spec_par += '\xCA' + berlv( self.par_sys_sim )
        sys_spec_par = '\xEF' + berlv( sys_spec_par )

        app_spec_par = 'par_applet' in self.__dict__ \
                       and self.par_applet or ''
        app_spec_par = '\xC9' + berlv( app_spec_par )

        uicc_spec = []
        if 'par_UICC_toolkit' in self.__dict__:
            uicc_spec.append( '\x80' + berlv( self.par_UICC_toolkit ))
        if 'par_UICC_DAP' in self.__dict__:
            uicc_spec.append( '\xC3' + berlv( self.par_UICC_DAP ))
        if 'par_UICC_access' in self.__dict__:
            uicc_spec.append( '\x81' + berlv( self.par_UICC_access ))
        if 'par_UICC_admin_access' in self.__dict__:
            uicc_spec.append( '\x82' + berlv( self.par_UICC_admin_access ))
        if uicc_spec:
            uicc_sys_par = ''.join( uicc_spec )
            uicc_sys_par = '\xEA' + berlv( uicc_sys_par )
        else:
            uicc_sys_par = ''

        AID_inst = 'AID_instance' in self.__dict__ \
                   and self.AID_instance or self.AID_module

        params = app_spec_par + sys_spec_par + uicc_sys_par
        if token:
            params += token.getCRT()
        data = berlv( self.AID_package ) + \
               berlv( self.AID_module ) + \
               berlv( AID_inst ) + \
               berlv( privileges ) + \
               berlv( params )
        if token:
            data2sign = pack( "BBB", P1_INST_INSMSEL, 0, len( data )) + data 
            data += berlv( token.calc( data2sign ))
        else:
            data += '\0'
        
        assert len( data ) < 0x100, "Data longer than 0xFF: 0x%X '%s'" % \
                              ( len(data), hexlify( data ).upper())

        apdu = [ 0x80, INS_INSTALL,  P1_INST_INSMSEL, 0, len( data ) ] + \
               [ ord( x ) for x in data ]
        return apdu

    def load( self, datalen = 239, token = None ):
        """ Build list of APDUs for InstallForLoad and Load.
  datalen      - data length in Load APDUs
  token        - instance of Token, calculates token for Delegated
                 management if present"""
        f = open( self.file_ijc, "rb" )
        ijc_data = f.read()
        ijc_len = len( ijc_data )
        h = hashlib.new( 'sha1' )
        h.update( ijc_data )
        ijc_hash = h.digest()
        print "Loading '%s', len = %d, SHA1 = %s" % \
            ( self.file_ijc, ijc_len, hexlify( ijc_hash ).upper())
        load_data = '\xC4' + berlv( ijc_data )

        # build Install for load APDU
        if ijc_len < 0x8000:
            params = '\xC6' + berlv( pack( ">H", ijc_len ))
        else:
            params = '\xC6' + berlv( pack( ">L", ijc_len ))
        if 'par_sys' in self.__dict__:
            params += ''.join( self.par_sys )
        else:
            params += unhexlify( "C8020000C7020000" )
        params = '\xEF' + berlv( params )
        if token:
            params += token.getCRT()

        AID_SD = self.__dict__.get( 'AID_SD', '' )
        data = berlv( self.AID_package ) + \
               berlv( AID_SD ) + \
               berlv( ijc_hash ) + \
               berlv( params )

        if token:
            data2sign = pack( "BBB", P1_INST_LOAD, 0, len( data )) + data 
            data += berlv( token.calc( data2sign ))
        else:
            data += '\0'

        assert len( data ) < 0x100, "Data longer than 0xFF: 0x%X '%s'" % \
                              ( len(data), hexlify( data ).upper())
        apdus = [ [ 0x80, INS_INSTALL, 2, 0, len( data ) ] +
                  [ ord(x) for x in data ]]

        # build Load APDUs
        napdu = ( len( load_data ) + datalen-1 ) / datalen
        P1 = 0
        for i in xrange( napdu ):
            if i == napdu-1: # the last block
                P1 = 0x80
                datalen = len( load_data )
            apdus.append( [ 0x80, INS_LOAD, P1, i, datalen ] +
                          [ ord(x) for x in load_data[:datalen]] )
            load_data = load_data[datalen:]

        return apdus

    def doDelete( self, aid, P2, token ):
        """ Build delete APDU (either package or instance )
  token        - instance of Token, calculates token for Delegated
                 management if present"""
        data = '\x4F' + berlv( aid )
        if token:
            data += token.getCRT()
            data2sign = pack( "BBB", 0, P2, len( data )) + data
            data += '\x9E' + berlv( token.calc( data2sign ))
        apdu = [ 0x80, INS_DELETE, 0, P2, len( data )] + \
               [ ord(x) for x in data ]
        return apdu
        
    def delete_package( self, zRelated = False, token = None ):
        """ Delete package and (if zRelated true) related instances.
  token        - instance of Token, calculates token for Delegated
                 management if present"""
        return self.doDelete( self.AID_package, zRelated and 0x80 or 0,
                              token )

    def delete_inst( self, token = None ):
        """ Delete instance.
  token        - instance of Token, calculates token for Delegated
                 management if present"""
        AID_inst = 'AID_instance' in self.__dict__ \
                   and self.AID_instance or self.AID_module
        return self.doDelete( AID_inst, 0, token )

    def install_extradict( self, aid_sd, token = None ):
        """ Build install for extradiction APDU
  aid_sd       - AID of SD to extradite to/from
  token        - instance of Token, calculates token for Delegated
                 management if present
 """
        assert 5 <= len( aid_sd ) and len( aid_sd ) <= 16
        AID_inst = 'AID_instance' in self.__dict__ \
                   and self.AID_instance or self.AID_module

        params = token and token.getCRT() or ''
        data = berlv( aid_sd ) + '\0' + berlv( AID_inst ) + '\0' +\
               berlv( params )

        if token:
            data2sign = pack( "BBB", P1_INST_EXTRA, 0, len( data )) + data 
            data += berlv( token.calc( data2sign ))
        else:
            data += '\0'
        assert len( data ) < 0x100, "Data longer than 0xFF: 0x%X '%s'" % \
                              ( len(data), hexlify( data ).upper())
        apdu = [ 0x80, INS_INSTALL, P1_INST_EXTRA, 0, len( data ) ] +\
               [ ord(x) for x in data ]
        return apdu

    def install_perso( self ):
        """ Build install for perso APDU """
        AID_inst = 'AID_instance' in self.__dict__ \
                   and self.AID_instance or self.AID_module
        data = '\0\0' + berlv( AID_inst ) + '\0\0\0'
        apdu = [ 0x80, INS_INSTALL, P1_INST_PERSO, 0, len( data ) ] +\
               [ ord(x) for x in data ]
        return apdu

class Token:
    """ Token processor """
    CRTtags = ( 't42', 't45', 't5F20', 't93' )
    def __init__( self, **kw ):
        """ Constructor, expects tags for Control Reference Template"""
        for t in Token.CRTtags:
            if t in kw:
                self.__dict__[t] = kw[t]
    def getCRT( self ):
        """ Build CRT (B6 TLV) for token calculation"""
        data = ''
        for t in Token.CRTtags:
            if t in self.__dict__:
                data += unhexlify(t[1:]) + berlv( self.__dict__[t] )
        if data:
            return '\xB6' + berlv( data )
        else:
            return ''
                
class DEStoken( Token ):
    """ DES token as defined in Global Platform Card Specification 2.2 AmA"""
    def __init__( self, key, **kw ):
        """ Constructor, key is 3DES2k, kw is dict of CRT paramters."""
        super( DEStoken, self ).__init__( **kw )
        assert len( key ) == 16, "3DES key must be 16B long"
        self.e = DES.new( key[:8], DES.MODE_ECB )
        self.d = DES.new( key[8:], DES.MODE_ECB )

    def calc( self, s ):
        " Pad string and calculate MAC according to B.1.2.2 - " +\
            "Single DES plus final 3DES """
        s = pad80( s )
        q = len( s ) / 8
        h = '\0'*8   # zero ICV
        for i in xrange(q):
            h = self.e.encrypt( bxor( h, s[8*i:8*(i+1)] ))
        h = self.d.decrypt( h )
        h = self.e.encrypt( h )
        return h
        
class RSAtoken( Token ):
    """ RSA token as defined in Global Platform Card Specification 2.2.1 C.4"""
    def __init__( self, **kw ):
        """ Constructor, kw is dict of CRT paramters and RSA key.
Required RSA priv. key params (as long)
 n, d, e - modulus and private exponent
or
 p, q, e - primes p, q, and public exponent e
If also dp, dq, qinv present, they are checked to be consistent.
Default value for e is 0x10001
"""
#        super( RSAtoken, self ).__init__( **kw )
        Token.__init__( self, **kw )
        # check RSA parameters
        for par in ( 'n', 'd', 'e', 'p', 'q', 'dp', 'dq', 'dqinv' ):
            if par in kw:
                assert isinstance( long( kw[par] ), long ), \
                    "RSA parameter %s must be long" % par
        e = long( kw.get( 'e', 0x10001L ))
        if 'n' in kw and 'd' in kw:
            self.key = RSA.construct(( n, e, d ))
        elif 'p' in kw and 'q' in kw:
            p = kw['p']
            q = kw['q']
            n = p*q
            d = number.inverse( e, (p-1)*(q-1))
            if 'd' in kw:
                assert d == kw['d'], "Inconsinstent private exponent"
            if 'dp' in kw:
                assert d % (p-1) == kw['dp'], "Inconsistent d mod (p-1)"
            if 'dq' in kw:
                assert d % (q-1) == kw['dq'], "Inconsistent d mod (q-1)"
            u = number.inverse( q, p )
            if 'qinv' in kw:
                assert u == kw['qinv'], "Inconsistent q inv"
            self.key = RSA.construct(( n, e, d, q, p, u ))
    def calc( self, s ):
        mhash = SHA.new( s )
        signer = PKCS1_v1_5.new( self.key )
        return signer.sign( mhash )

