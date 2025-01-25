class Character(AbstractObject):   
    is_fictional = db.Column(db.Boolean, default=False)

    # birth_date
    # death_date

    # portraits

    # roles
    # factions

    # links = array of strings

    # @hybrid_property
    # def last_faction(self):
    #     return self.factions[-1]

    def __repr__(self):
        return f'<Character {self.name}>'

#class Portrait
    # source
    # path

#class Role (Tag)

# class Faction (Tag)
    # leaders