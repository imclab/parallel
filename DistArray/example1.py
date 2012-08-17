import cdms2
import MV2
import distarray
import numpy
import cdutil
from mpi4py import MPI
import sys

# open file and read data
try:
    clt = cdms2.open('/usr/local/uvcdat/1.0.0/sample_data/clt.nc', 'r')['clt']
except:
    clt = cdms2.open('/home/pletzer/uvcdat/cdat/install/sample_data/clt.nc', 'r')['clt']

def getPrimeFactors(n):
    lo = [1]
    n2 = n // 2
    k = 2
    while k <= n2:
        if (n // k)*k == n:
            lo.append(k)
        k += 1
    return lo + [n,]

def getDomainDecomp(nprocs,sizes):
    latPrimeNumbers = getPrimeFactors(sizes[0])
    lonPrimeNumbers = getPrimeFactors(sizes[1])
    lonPrimeNumbers.reverse()
    for plat in latPrimeNumbers:
        for plon in lonPrimeNumbers:
            if plat * plon == nprocs:
                return [plat, plon]
    return None, None

nLat,nLon = clt.shape[1:]
rk = MPI.COMM_WORLD.Get_rank()
sz = MPI.COMM_WORLD.Get_size()

npLat,npLon = getDomainDecomp(sz,(nLat,nLon))
if npLat is None or npLon is None:
    print 'could not find a domain decomp for this number of procs'
    sys.exit(1)

if rk == 0:
    print 'domain decomp: ', npLat, ' x ', npLon

value=0
cdms2.setNetcdfShuffleFlag(value) ## where value is either 0 or 1
cdms2.setNetcdfDeflateFlag(value) ## where value is either 0 or 1
cdms2.setNetcdfDeflateLevelFlag(value) ## where value is a integer between 0 and 9 included
if rk == 0:
    print "nlon,nlat:",nLat,nLon
print rk,"nps:",npLat,npLon

nlat,nlon = nLat/npLat , nLon/npLon
ipLat = rk // npLon
ipLon = rk % npLon

iLatBeg , iLatEnd = ipLat * nlat, (ipLat+1) * nlat
iLonBeg , iLonEnd = ipLon * nlon, (ipLon+1) * nlon
print '[%d] sub-domain slab: %d:%d, %d:%d dims %d x %d size: %d' % (rk, iLatBeg, iLatEnd, iLonBeg, iLatEnd, iLatEnd - iLatBeg, iLonEnd - iLonBeg, (iLatEnd - iLatBeg)*(iLonEnd - iLonBeg))

daclt = clt[:,iLatBeg:iLatEnd,iLonBeg:iLonEnd]
cdutil.setTimeBoundsMonthly(daclt)
print rk,daclt.shape
mp = cdutil.averager(daclt,axis='t')


if rk==0:
    print "Gathering results"
lst = MPI.COMM_WORLD.gather(mp,root=0)
if rk==0:
    print "Gathered"
    out = numpy.zeros(clt.shape[1:],clt.dtype)
    for proc in range(sz):
        print len(lst),proc,lst[proc].shape
    for proc in range(sz):
        ipLat = proc // npLon
        ipLon = proc % npLon
        iLatBeg , iLatEnd = ipLat * nlat, (ipLat+1) * nlat
        iLonBeg , iLonEnd = ipLon * nlon, (ipLon+1) * nlon
        out[iLatBeg:iLatEnd,iLonBeg:iLonEnd] = lst[proc]

    lat = clt.getLatitude()
    lon = clt.getLongitude()

    out= MV2.array(out)
    print out.shape
    out.setAxis(0,lat)
    out.setAxis(1,lon)
    f=cdms2.open("map.nc","w")
    f.write(out,id=clt.id)
    f.close()
    
    import vcs
    x=vcs.init()
    x.plot(out)
    raw_input()

    if False:
        from matplotlib import pylab
        pylab.pcolor(out)
        for proc in range(sz):
            ipLat = proc // npLon
            ipLon = proc % npLon
            iLatBeg , iLatEnd = ipLat * nlat, (ipLat+1) * nlat
            iLonBeg , iLonEnd = ipLon * nlon, (ipLon+1) * nlon        
            pylab.plot([0, nLon], [iLatBeg, iLatBeg], 'w')
            pylab.plot([iLonBeg, iLonBeg], [0, nLat], 'w')
        pylab.show()
    