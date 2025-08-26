import segyio

import numpy as np


__all__ = ['count_segy_shots', 'get_velocity_model', 'ReadSEGY2D']


def count_segy_shots(segy_path, shotattr=segyio.TraceField.FieldRecord):
    with segyio.open(segy_path, "r", ignore_geometry=True) as segyfile:
        headers = segyfile.header
        shotpoints = [trace[shotattr] for trace in headers]

        shot_ids = set(shotpoints)
        return len(shot_ids), list(shot_ids)


def get_velocity_model(model_path):
    """
    Read velocity model from a SEGY file
    """
    f = segyio.open(model_path, iline=segyio.tracefield.TraceField.FieldRecord,
                    xline=segyio.tracefield.TraceField.CDP)

    xl, il, t = f.xlines, f.ilines, f.samples
    if len(il) != 1:
        dims = (len(xl), len(il), len(t))
    else:
        dims = (len(xl), len(t))

    vp = f.trace.raw[:].reshape(dims)
    return vp, dims


class ReadSEGY2D():

    def __init__(self, segy_path, mpi=None, shot_ids=None):

        self.segyfile = segy_path
        self.controller = mpi
        self.table, self.indexes = self.make_lookup_table(segy_path, mpi, shot_ids)
        self.isRecVariable = self._isRecVariable()
        self.nsrc = len(self.table)

    def _isRecVariable(self):
        """
        Verify if the number of receivers per shots is Regular.

        return True if all shots has the same number of receivers, and False otherwise
        """
        # get a set of values representing the number of traces per shot. In other words, the number os receivers per shot
        n_traces_per_shots = set(v["Num_Traces"] for v in self.table.values())

        # If the lenght of the set is 1, means that all the shots has the same number os receivers
        return len(n_traces_per_shots) != 1

    def make_lookup_table(self, sgy_file, mpi_controller, sampled_ids):
        '''
        Make a lookup of shots, where the keys are the shot record IDs being
        searched (looked up)

        Made by Oscar Mojica
        '''
        indexes = []
        lookup_table = {}

        samples = sampled_ids if not mpi_controller else mpi_controller.shot_ids

        with segyio.open(sgy_file, ignore_geometry=True) as f:
            index = None
            pos_in_file = 0

            for header in f.header:
                index = header[segyio.TraceField.FieldRecord]

                if (samples and (index not in samples)):
                    pos_in_file += 1
                    continue

                if int(header[segyio.TraceField.SourceGroupScalar]) < 0:
                    scalco = abs(1. / header[segyio.TraceField.SourceGroupScalar])
                else:
                    scalco = header[segyio.TraceField.SourceGroupScalar]
                # Esses comentários são temporários, scalel voltará a ser utilizado
                # if int(header[segyio.TraceField.ElevationScalar]) < 0:
                #     scalel = abs(1. / header[segyio.TraceField.ElevationScalar])
                # else:
                #     scalel = header[segyio.TraceField.ElevationScalar]
                # Check to see if we're in a new shot

                if index not in lookup_table.keys():
                    indexes.append(index)
                    lookup_table[index] = {}
                    lookup_table[index]['filename'] = sgy_file
                    lookup_table[index]['Trace_Position'] = pos_in_file
                    lookup_table[index]['Num_Traces'] = 1
                    lookup_table[index]['Source'] = (header[segyio.TraceField.SourceX] * scalco, header[segyio.TraceField.SourceY] * scalco)
                    lookup_table[index]['Receivers'] = []
                else:  # Not in a new shot, so increase the number of traces in the shot by 1
                    lookup_table[index]['Num_Traces'] += 1
                lookup_table[index]['Receivers'].append((header[segyio.TraceField.GroupX] * scalco, header[segyio.TraceField.GroupY] * scalco))
                pos_in_file += 1

        return lookup_table, indexes

    def getVelocityModel(self, path):
        """
        Read velocity model from a SEGY file
        """
        return get_velocity_model(path)

    def getsourceData(self, path):
        """
        Read source data from a SEGY file
        """
        f = segyio.open(path, iline=segyio.tracefield.TraceField.FieldRecord,
                        xline=segyio.tracefield.TraceField.CDP)

        src_data = f.trace.raw[:]
        return src_data

    def getSourceCoords(self, index=0):
        src_coords = np.array(self.table[index]['Source'])
        sx = np.array([src_coords[0]])
        sz = np.array([src_coords[-1]])

        return sx, sz

    def getReceiverCoords(self, index=0):
        recs_coords = np.array(self.table[index]['Receivers'])
        rx = np.array([coord[0] for coord in recs_coords])
        rz = np.array([coord[-1] for coord in recs_coords])

        return rx, rz

    def getCoords(self, index=0):
        rec_coords = self.getReceiverCoords(index)
        src_coords = self.getSourceCoords(index)

        return src_coords, rec_coords

    def getTn(self):
        with segyio.open(self.segyfile, "r", ignore_geometry=True) as f:
            num_samples = len(f.samples)
            samp_int = f.bin[segyio.BinField.Interval] / 1000

        return (num_samples - 1) * samp_int

    def getDt(self):
        with segyio.open(self.segyfile, "r", ignore_geometry=True) as f:
            dt = f.bin[segyio.BinField.Interval]  # microseconds
        return dt / 1000  # return in miliseconds

    def getData(self, index: int):
        """
        Return the data from a specific index. It need to add a dimension to match returned data from _Wave
        Parameters
        ----------
        index : :obj:`int`
            Index of the shot that it will get the data
        """
        with segyio.open(self.segyfile, "r", ignore_geometry=True) as f:
            position = self.table[index]['Trace_Position']
            traces_in_shot = self.table[index]['Num_Traces']

            num_samples = len(f.samples)
            retrieved_shot = np.zeros((1, traces_in_shot, num_samples), dtype=np.float32)

            shot_traces = f.trace[position:position + traces_in_shot]

            for ii, trace in enumerate(shot_traces):
                retrieved_shot[:, ii] = trace
        return retrieved_shot

    def getMinCoords(self):
        """
        Get the origin of the survey. It is the minimum value of the source and receiver coordinates
        """
        minX = np.inf
        minY = np.inf
        for isrc in self.indexes:
            src_coords, rec_coords = self.getCoords(isrc)

            minX = min(minX, np.min(src_coords[0]), np.min(rec_coords[0]))
            minY = min(minY, np.min(src_coords[1]), np.min(rec_coords[1]))

        return minX, minY
