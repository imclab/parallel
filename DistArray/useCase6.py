##UVCDAT use case 6
##Compute hybrid to std plevs


#!/usr/bin/env python

"""
From Michael Wehner, modified to run in parallel by Alex Pletzer (Tech-X)

To run this script, cpopy the following data:
hopper.nersc.gic:/project/projectdirs/vacet/Wehner/uvcdat_tests/

PS_cam5_1_amip_run2.cam2.h0.1994.nc
V_cam5_1_amip_run2.cam2.h0.1994.nc
cam5_1_amip_run2.cam2.h0.2002-09.nc

To execute the script:

time mpiexec -n 12 useCase6.py ./ V_cam5_1_amip_run2.cam2.h0.1994.nc V cam5_1_amip_run2.cam2.h0.2002-09.nc PS_cam5_1_amip_run2.cam2.h0.1994.nc 1000, 925, 850, 700, 600, 500, 400, 300, 250, 200, 150, 100, 70, 50, 30, 20, 10

On multipole.txcorp.com 
Linux multipole.txcorp.com 2.6.32-220.17.1.el6.x86_64 #1 SMP Wed May 16 00:01:37 BST 2012 x86_64 x86_64 x86_64 GNU/Linux
has 8 procs AMD Opteron(tm) Processor 4130 2.6Ghz

1 proc: 
real	16m50.452s
user	15m49.897s
sys	0m38.921s

4 procs:
real	5m25.258s
user	20m0.773s
sys	0m49.133s

6 procs:
real	4m35.794s
user	22m10.534s
sys	3m44.607s

12 procs:
real	5m36.064s
user	24m55.288s
sys	9m30.538s

Note: there are 12 time steps. Parallelization is over time. There is a critical
region where the data are written to the Netcdf file in order. Further improvement
in scaling can be obtained by having each processor write to a different file.

"""


# Adapted for numpy/ma/cdms2 by convertcdms.py
import numpy.oldnumeric as Numeric
# Input arguments to the script

from mpi4py import MPI

import sys,numpy.ma as MA,string,cdms2 as cdms,cdtime,cdutil,numpy.oldnumeric as Numeric
from cdtime import reltime
# reset DefaultCalendar below
cdtime.DefaultCalendar=cdtime.NoLeapCalendar

cdms.setNetcdfShuffleFlag(0)
cdms.setNetcdfDeflateFlag(0)
cdms.setNetcdfDeflateLevelFlag(0)

pth=sys.argv[1]
infile=sys.argv[2]
varin=sys.argv[3]
ABfile=sys.argv[4]
outfile='y'+sys.argv[2]
varout=varin
psfile=sys.argv[5]
levels=string.join(sys.argv[6:])

Avar='hyam'
Bvar='hybm'
P0var='P0'

varps='PS'
levels=string.join(sys.argv[6:])
levels=eval(levels)  # evaluate the string
levels=MA.asarray(list(levels))*100.
# Define some neat function

def getMetadata(s,**args):
  return s.getAxisList(**args),s.attributes
##   return apply(s.getAxisList,(),**args),s.attributes


def putMetadata(meta,tv,**args):
  import cdms2 as cdms
  if cdms.isVariable(meta) : meta=getMetadata(meta,**args)
  return cdms.createVariable(tv,axes=meta[0],attributes=meta[1])


def asMA(b,**keyargs):
  '''Converts a list of MAs to an MA
  Version 1.0 - February 28th, 2001
  Author Paul Dubois (dubois1@llnl.gov)
  '''
  import numpy.ma as MA
  m = [MA.getmaskarray(x) for x in b]
  b = [MA.filled(x) for x in b]
  return MA.array(b, mask=m,**keyargs)


def make_P(ps,A,B,P0):
    '''
    # Author Charles Doutriaux
    # Version 1.0
    # email: doutriaux1@llnl.gov
    # Step 1 of conversion of a field from sigma levels to pressure levels
    # Create the Pressure field on sigma levels, from the surface pressure
    
    # Input
    # Ps   : Surface pressure
    # A,B,Po: Coefficients, such as: p=B.ps+A.Po
    # Ps is 2D (lonxlat)
    # B,A are 1D (vertical sigma levels)

    # Output
    # Pressure field from TOP (level 0) to BOTTOM (last level)
    # 3D field (lon/lat/sigma)

    # External : Numeric
    
    # Compute the pressure for the sigma levels'''
    import numpy.ma as MA
    p=MA.outerproduct(B,ps)
    dim=B.shape[0],ps.shape[0],ps.shape[1]
    p=MA.reshape(p,dim)
##     p=ps.filled()[Numeric.NewAxis,...]*B.filled()[:,Numeric.NewAxis,Numeric.NewAxis]
##     Po=P0*MA.ones(p.shape,Numeric.Float)
    A=MA.outerproduct(A,P0*MA.ones(p.shape[1:]))
    A=MA.reshape(A,p.shape)
    p=p+A
    # Now checking to make sure we return P[0] as the top
    a=MA.average(MA.average(p[0]-p[-1], axis=0))
    if a>0:
        # We got the wrong order !
        p=p[::-1]
    return p
    
def log_linear_vinterp(T,P,levs):
    '''
    # Author Charles Doutriaux
    # Version 1.1
    # Expect 2D field here so there''s no reorder which I suspect to do a memory leak
    # email: doutriaux1@llnl.gov
    # Converts a field from sigma levels to pressure levels
    # Log linear interpolation


    # Input
    # T :    temperature on sigma levels
    # P :    pressure field from TOP (level 0) to BOTTOM (last level)
    # levs : pressure levels to interplate to (same units as P)

    # Output
    # t :    temperature on pressure levels (levs)

    # External: Numeric'''
    import numpy.ma as MA
##     from numpy.oldnumeric.ma import ones,Float,greater,less,logical_and,where,equal,log,asarray,Float16
    sh=P.shape
    nsigma=sh[0] # Number of sigma levels
    try:
        nlev=len(levs)  # Number of pressure levels
    except:
        nlev=1  # if only one level len(levs) would breaks
    t=[]
    for ilv in range(nlev): # loop through pressure levels
        try:
            lev=levs[ilv] # get value for the level
        except:
            lev=levs  # only 1 level passed
#       print '          ......... level:',lev
        Pabv=MA.ones(P[0].shape,Numeric.Float)
        Tabv=-Pabv # Temperature on sigma level Above
        Tbel=-Pabv # Temperature on sigma level Below
        Pbel=-Pabv # Pressure on sigma level Below
        Pabv=-Pabv # Pressure on sigma level Above
        for isg in range(1,nsigma): # loop from second sigma level to last one
##             print 'Sigma level #',isg
            a = MA.greater(P[isg],  lev) # Where is the pressure greater than lev
            b = MA.less(P[isg-1],lev)    # Where is the pressure less than lev

            # Now looks if the pressure level is in between the 2 sigma levels
            # If yes, sets Pabv, Pbel and Tabv, Tbel
            Pabv=MA.where(MA.logical_and(a,b),P[isg],Pabv) # Pressure on sigma level Above
            Tabv=MA.where(MA.logical_and(a,b),T[isg],Tabv) # Temperature on sigma level Above
            Pbel=MA.where(MA.logical_and(a,b),P[isg-1],Pbel) # Pressure on sigma level Below
            Tbel=MA.where(MA.logical_and(a,b),T[isg-1],Tbel) # Temperature on sigma level Below
        # end of for isg in range(1,nsigma)
#       val=where(equal(Pbel,-1.),Pbel.missing_value,lev) # set to missing value if no data below lev if there is
        
        tl=MA.masked_where(MA.equal(Pbel,-1.),MA.log(lev/MA.absolute(Pbel))/MA.log(Pabv/Pbel)*(Tabv-Tbel)+Tbel) # Interpolation
        t.append(tl) # add a level to the output
    # end of for ilv in range(nlev)
    return asMA(t).astype(Numeric.Float32) # convert t to an array



# Gets the coef from the AB file
#print 'Getting coeff'
f=cdms.open(ABfile)
A=f(Avar)
B=f(Bvar)
Po=f(P0var)
#print 'Po:',Po
# open and get the surface pressure
#print 'Getting surface pressure'
fps=cdms.open(psfile)

# get var on sigma var (for ex T)
#print 'Getting T !'
fi=cdms.open(infile)
tt=fi.dimensionobject('time')
if tt.calendar=='360_day':cdtime.DefaultCalendar=cdtime.Calendar360
if tt.calendar=='gregorian':cdtime.DefaultCalendar=cdtime.MixedCalendar
if tt.calendar=='365_day':cdtime.DefaultCalendar=cdtime.NoLeapCalendar
if tt.calendar=='noleap':cdtime.DefaultCalendar=cdtime.NoLeapCalendar
if tt.calendar=='proleptic_gregorian':cdtime.DefaultCalendar=cdtime.GregorianCalendar
if tt.calendar=='standard':cdtime.DefaultCalendar=cdtime.StandardCalendar

v=fi.variables[varin]
meta=getMetadata(v)
tim=v.getTime()
u=tim.units

nprocs = MPI.COMM_WORLD.Get_size()
myPe = MPI.COMM_WORLD.Get_rank()
ranks = [rk%nprocs for rk in range(len(tim))]
outs = [None for rk in range(len(tim))]
if myPe == 0:
  print 'ranks = ', ranks

itim=0
for tm in tim[:]: # loop over time
 
    if ranks[itim] == myPe:

      T=v(time=(tm))
      T=MA.average(T, axis=0)
      Ps=fps.getslab(varps,tm,tm)
      Ps=MA.average(Ps, axis=0)

      # create the pressure field
      P=make_P(Ps,A,B,Po)

      # interpolate
      print '[%d] Interpolating at time index %d' % (myPe, itim)
      out=log_linear_vinterp(T,P,levels)
      print '[%d] Done!' % myPe
      sh=list(out.shape)
      sh.insert(0,1)
      out=MA.reshape(out,tuple(sh))
      t=tim.subAxis(itim,itim+1)
      xx=reltime(tim[itim],tim.units)
      t_new=xx.torel('days since 1800').value
      t[0]=t_new
      t.units='days since 1800'
      meta[0][0]=t
      levelsax=cdms.createAxis(levels/100.)
      levelsax.id='plev'
      levelsax.units='hPa'
      levelsax.designateLevel()
      meta[0][1]=levelsax
      out=putMetadata(meta,out)
      out.id=varout
      cdutil.times.setTimeBoundsDaily(out)
      outs[itim] = out
    
    itim += 1

for itim in range(len(tim)):
    out = outs[itim]
    if out is not None: 
        if itim==0:
            f=cdms.open(outfile,'w')
        else:
            f=cdms.open(outfile,'r+')
        print '[%d] Writing data for itim = %d...' % (myPe, itim)
        f.write(out,axes=out.getAxisList(),id=out.id)
        print '[%d] Done!' % myPe
        f.close()
    
    # make sure the data are written in order
    MPI.COMM_WORLD.Barrier()
